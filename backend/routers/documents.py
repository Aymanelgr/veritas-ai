"""Upload, list, inspect, preview, reprocess and delete documents."""

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

import pymupdf
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend import insights, schemas
from backend.audit import record
from backend.deps import db, owned_document, require
from backend.corrections import active_corrections, apply_corrections, get_value
from backend.jobs import enqueue_processing, enqueue_verification
from backend.uploads import MAX_FILE_BYTES, MAX_FILES_PER_UPLOAD, RejectedUpload, check_file
from db.models import Correction, Document, Finding, Link, ProcessingRun, User
from phase2_documents.reader import IMAGE_EXTENSIONS
from phase3_extraction.schemas import Extraction
from phase4_matching.matcher import Link as Proposal
from phase4_matching.matcher import align_items

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "uploads"

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _save_upload(stream: BinaryIO, name: str) -> tuple[Path, str, int]:
    """Stream the upload to a temporary file, stopping as soon as it exceeds the size limit."""
    digest, size = hashlib.sha256(), 0
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=UPLOAD_DIR, prefix=".incoming-")
    with tmp:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise RejectedUpload(f"{name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
            digest.update(chunk)
            tmp.write(chunk)
    return Path(tmp.name), digest.hexdigest(), size


def store_file(session: Session, user: User | None, organization_id: int, name: str, stream: BinaryIO,
               overrides: dict | None = None, source: dict | None = None) -> Document:
    """Validate and store one file as a new document (not yet processed). Raises RejectedUpload.

    Used by uploads and by the email intake, so both get the same content checks and limits.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(name or "upload").name
    tmp, sha256, size = _save_upload(stream, name)
    try:
        checked = check_file(tmp, Path(name).suffix)
    except RejectedUpload:
        tmp.unlink(missing_ok=True)
        raise
    # A random prefix stops two uploads with the same name from overwriting each other.
    path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{name}"
    shutil.move(tmp, path)
    doc = Document(organization_id=organization_id, uploaded_by_id=user.id if user else None, filename=name,
                   file_path=str(path), sha256=sha256, size_bytes=size, content_type=checked.content_type,
                   overrides=overrides or {})
    session.add(doc)
    session.flush()
    record(session, user, "document_uploaded", "document", doc.id, organization_id=organization_id,
           filename=name, sha256=sha256, **(source or {}))
    session.commit()
    return doc


def _overrides(doc_type: str | None, language: str | None, currency: str | None,
               day_first: str | None) -> dict:
    """What the user told us about the documents; "auto" or empty means: detect it."""
    body = schemas.OverridesIn(doc_type=doc_type or None, language=language or None, currency=currency or None,
                               day_first=None if day_first in (None, "", "auto") else day_first == "true")
    return {k: v for k, v in body.model_dump().items() if v not in (None, "auto")}


@router.post("", status_code=202)
def upload(files: list[UploadFile], doc_type: str | None = Form(None), language: str | None = Form(None),
           currency: str | None = Form(None), day_first: str | None = Form(None),
           user: User = Depends(require("reviewer")), session: Session = Depends(db)) -> list[schemas.DocumentOut]:
    overrides = _overrides(doc_type, language, currency, day_first)
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(413, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")
    created = []
    for file in files:
        name = Path(file.filename or "upload").name
        try:
            created.append(store_file(session, user, user.organization_id, name, file.file, overrides))
        except RejectedUpload as error:
            raise HTTPException(415, f"{name}: {error}") from None
    for doc in created:
        enqueue_processing(doc.id)  # 202 Accepted: processing continues in the background
    for doc in created:
        session.refresh(doc)
    return [schemas.DocumentOut.model_validate(d) for d in created]


def _open_findings(session: Session, organization_id: int) -> dict[int, int]:
    rows = session.execute(
        select(Finding.document_id, func.count()).join(Document, Finding.document_id == Document.id)
        .where(Finding.review_status == "pending", Document.organization_id == organization_id)
        .group_by(Finding.document_id))
    return dict(rows.all())


@router.get("")
def list_documents(limit: int = 200, offset: int = 0, user: User = Depends(require("viewer")),
                   session: Session = Depends(db)) -> list[schemas.DocumentOut]:
    counts = _open_findings(session, user.organization_id)
    docs = session.scalars(select(Document).where(Document.organization_id == user.organization_id)
                           .order_by(Document.created_at.desc(), Document.id.desc())
                           .limit(min(limit, 500)).offset(offset)).all()
    return [schemas.DocumentOut.model_validate(d).model_copy(update={"open_findings": counts.get(d.id, 0)})
            for d in docs]


def _comparison(session: Session, invoice: Document, orders: list[Document]) -> schemas.Comparison:
    """The invoice's items next to the items of its order(s), using the same alignment as verification."""
    from backend.pipeline import record_for

    inv = record_for(session, invoice).data
    order_data = [record_for(session, po).data for po in orders]
    order_lines = [item for data in order_data for item in data.line_items]
    currencies = {inv.currency, *(d.currency for d in order_data)}
    money_ok = len(currencies) == 1 and None not in currencies
    pairs = align_items(inv.line_items, order_lines)
    rows = []
    for i, k, _ in sorted(pairs, key=lambda p: p[1]):  # in order-line order
        a, b = inv.line_items[i], order_lines[k]
        same = a.quantity == b.quantity and (not money_ok or a.unit_price == b.unit_price)
        rows.append(schemas.ComparisonRow(
            description=b.description, ordered_quantity=b.quantity, invoiced_quantity=a.quantity,
            ordered_price=b.unit_price, invoiced_price=a.unit_price, status="match" if same else "mismatch"))
    matched_inv, matched_po = {i for i, _, _ in pairs}, {k for _, k, _ in pairs}
    rows += [schemas.ComparisonRow(description=b.description, ordered_quantity=b.quantity,
                                   ordered_price=b.unit_price, status="not_invoiced")
             for k, b in enumerate(order_lines) if k not in matched_po]
    rows += [schemas.ComparisonRow(description=a.description, invoiced_quantity=a.quantity,
                                   invoiced_price=a.unit_price, status="unexpected")
             for i, a in enumerate(inv.line_items) if i not in matched_inv]
    totals = [d.total for d in order_data]
    return schemas.Comparison(
        purchase_order_id=orders[0].id, purchase_order_number=", ".join(o.number or o.filename for o in orders),
        rows=rows, ordered_total=sum(totals) if None not in totals else None, invoiced_total=inv.total,
        currency=inv.currency if money_ok else None, money_comparable=money_ok)


@router.get("/{document_id}")
def get_document(document_id: int, user: User = Depends(require("viewer")),
                 session: Session = Depends(db)) -> schemas.DocumentDetail:
    doc = owned_document(session, user, document_id)
    links, usable_orders = [], []
    for link in session.scalars(select(Link).where(
            or_(Link.invoice_id == doc.id, Link.purchase_order_id == doc.id)).order_by(Link.id)):
        is_invoice = link.invoice_id == doc.id
        other = session.get(Document, link.purchase_order_id if is_invoice else link.invoice_id)
        strength = Proposal(invoice="", purchase_order="", score=link.score, reasons=[]).strength
        links.append(schemas.LinkOut(id=link.id, document_id=other.id, filename=other.filename, number=other.number,
                                     relation="purchase_order" if is_invoice else "invoice", score=link.score,
                                     strength=strength, reasons=link.reasons, status=link.status, method=link.method,
                                     note=link.note, decided_at=link.decided_at))
        if is_invoice and link.status in ("proposed", "confirmed") and other.extraction:
            usable_orders.append(other)
    findings = session.scalars(select(Finding).where(Finding.document_id == doc.id)
                               .order_by(Finding.id)).all()
    comparison = _comparison(session, doc, usable_orders) if usable_orders and doc.extraction else None
    runs = session.scalars(select(ProcessingRun).where(ProcessingRun.document_id == doc.id)
                           .order_by(ProcessingRun.id.desc()).limit(5)).all()
    base = schemas.DocumentOut.model_validate(doc).model_dump()
    corrections = list(session.scalars(select(Correction).where(Correction.document_id == doc.id)
                                       .order_by(Correction.id)))
    effective = apply_corrections(Extraction.model_validate(doc.extraction).data,
                                  [c for c in corrections if c.active]).model_dump(mode="json") if doc.extraction else None
    return schemas.DocumentDetail(
        **base, text=doc.text, pages=doc.pages, extraction=doc.extraction, effective=effective, links=links,
        findings=[schemas.FindingOut.model_validate(f) for f in findings], comparison=comparison,
        corrections=[schemas.CorrectionOut.model_validate(c) for c in corrections],
        runs=[schemas.ProcessingRunOut.model_validate(r) for r in runs],
    )


@router.patch("/{document_id}/overrides")
def set_overrides(document_id: int, body: schemas.OverridesIn, user: User = Depends(require("reviewer")),
                  session: Session = Depends(db)) -> schemas.DocumentOut:
    """Tell Veritas the document type, language, currency or date order, and read it again."""
    doc = owned_document(session, user, document_id)
    previous = dict(doc.overrides or {})
    doc.overrides = {k: v for k, v in body.model_dump().items() if v not in (None, "auto")}
    doc.status = "uploaded"
    record(session, user, "document_overrides_changed", "document", doc.id, before=previous, after=doc.overrides)
    session.commit()
    enqueue_processing(doc.id)
    session.refresh(doc)
    return schemas.DocumentOut.model_validate(doc)


@router.post("/{document_id}/corrections", status_code=201)
def add_correction(document_id: int, body: schemas.CorrectionIn, user: User = Depends(require("reviewer")),
                   session: Session = Depends(db)) -> schemas.CorrectionOut:
    """Correct an extracted value, with a reason. The original stays recorded; checks are re-run."""
    doc = owned_document(session, user, document_id)
    if not doc.extraction:
        raise HTTPException(409, "The document has not been extracted yet")
    if not body.reason.strip():
        raise HTTPException(422, "Please give a reason for the correction")
    current = apply_corrections(Extraction.model_validate(doc.extraction).data, active_corrections(session, doc.id))
    try:
        original = get_value(current, body.field_path)
        apply_corrections(current, [Correction(field_path=body.field_path, new_value=body.value)])
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as error:
        raise HTTPException(422, f"Cannot set {body.field_path} to {body.value!r}: {error}") from None
    correction = Correction(document_id=doc.id, field_path=body.field_path, original_value=original,
                            new_value=body.value, reason=body.reason.strip(), user_id=user.id)
    session.add(correction)
    session.flush()
    record(session, user, "field_corrected", "document", doc.id, field=body.field_path, before=original,
           after=body.value, reason=body.reason)
    session.commit()
    enqueue_verification(doc.id)
    return schemas.CorrectionOut.model_validate(correction)


@router.delete("/{document_id}/corrections/{correction_id}", status_code=204)
def undo_correction(document_id: int, correction_id: int, user: User = Depends(require("reviewer")),
                    session: Session = Depends(db)) -> None:
    doc = owned_document(session, user, document_id)
    correction = session.get(Correction, correction_id)
    if correction is None or correction.document_id != doc.id:
        raise HTTPException(404, "Correction not found")
    correction.active = False  # kept in the history, no longer applied
    record(session, user, "correction_undone", "document", doc.id, field=correction.field_path)
    session.commit()
    enqueue_verification(doc.id)


@router.get("/{document_id}/file")
def get_file(document_id: int, user: User = Depends(require("viewer")),
             session: Session = Depends(db)) -> FileResponse:
    doc = owned_document(session, user, document_id)
    # "inline" lets the dashboard display PDFs and images instead of downloading them.
    return FileResponse(doc.file_path, filename=doc.filename, content_disposition_type="inline",
                        media_type=doc.content_type)


@router.get("/{document_id}/preview")
def preview(document_id: int, page: int = 1, user: User = Depends(require("viewer")),
            session: Session = Depends(db)) -> Response:
    """A page of the document as a PNG image, so every browser can display it."""
    doc = owned_document(session, user, document_id)
    suffix = Path(doc.file_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return FileResponse(doc.file_path)
    if suffix != ".pdf":
        raise HTTPException(404, "No preview for this file type")
    with pymupdf.open(doc.file_path) as pdf:
        if not 1 <= page <= pdf.page_count:
            raise HTTPException(404, "Page not found")
        png = pdf[page - 1].get_pixmap(dpi=110).tobytes("png")
    return Response(png, media_type="image/png")


@router.post("/{document_id}/reprocess", status_code=202)
def reprocess(document_id: int, full: bool = False, user: User = Depends(require("reviewer")),
              session: Session = Depends(db)) -> schemas.DocumentOut:
    """Run matching and checks again. The slow reading/extraction is reused for an unchanged
    file unless full=true (e.g. to read it again with a newer model)."""
    doc = owned_document(session, user, document_id)
    if full:
        doc.cache_key = None
    # Mark as queued right away, so clients polling the status see work is pending.
    doc.status = "uploaded"
    record(session, user, "document_reprocessed", "document", doc.id, full=full)
    session.commit()
    enqueue_processing(doc.id)
    session.refresh(doc)
    return schemas.DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, user: User = Depends(require("admin")),
                    session: Session = Depends(db)) -> None:
    doc = owned_document(session, user, document_id)
    record(session, user, "document_deleted", "document", doc.id, filename=doc.filename, sha256=doc.sha256)
    from backend.routers.assistant import forget_document

    forget_document(session, doc.organization_id, doc.id)
    Path(doc.file_path).unlink(missing_ok=True)
    session.delete(doc)
    session.commit()


@router.get("/{document_id}/timeline")
def get_timeline(document_id: int, user: User = Depends(require("viewer")),
                 session: Session = Depends(db)) -> list[dict]:
    """Orders, invoices, matches, findings, corrections and decisions of this transaction, in time order."""
    return insights.timeline(session, owned_document(session, user, document_id))


@router.post("/{document_id}/simulate")
def simulate(document_id: int, body: schemas.SimulateIn, user: User = Depends(require("viewer")),
             session: Session = Depends(db)) -> dict:
    """Which findings would change if these values were different. Nothing is saved."""
    doc = owned_document(session, user, document_id)
    if doc.doc_type != "invoice" or not doc.extraction:
        raise HTTPException(422, "Simulations run on a processed invoice")
    for change in body.changes:
        owned_document(session, user, change.document_id)
    try:
        result = insights.simulate(session, doc, [c.model_dump() for c in body.changes])
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as error:
        raise HTTPException(422, f"Cannot simulate this change: {error}") from None
    finally:
        session.rollback()  # belt and braces: a simulation never writes
    return result
