"""The processing pipeline for one uploaded document (runs in the worker).

    duplicate?  -> read (OCR) -> extract -> index -> identity/revisions -> match -> verify -> notify

Reliability rules
  - One document is never processed twice at the same time (a Redis lock).
  - The same file uploaded again is marked as a duplicate and not processed.
  - An unchanged file with unchanged settings and model versions reuses its earlier
    reading and extraction (the slow stages); matching and verification run again.
  - Every stage is timed and recorded (ProcessingRun), and the document shows its stage
    and page progress while it runs.
  - Reprocessing is idempotent: findings are matched by fingerprint, so a repeated run
    updates them instead of duplicating them, and keeps human review decisions. When a
    reviewed finding's evidence changes, the old decision is kept as "superseded".
  - Links decided by a person (confirmed / rejected / manual) are never changed by
    automatic matching.
  - Temporary failures (the local LLM not reachable) are retried by the job queue;
    other failures stop with a readable error. A notification failure never fails the
    document: it is recorded on the alert delivery instead.
"""

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
from redis.exceptions import LockError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.corrections import active_corrections, apply_corrections
from backend.identity import declares_revision, identity_key
from backend.jobs import JOB_TIMEOUT, redis
from db.models import AlertDelivery, Document, Finding, Link, OrganizationSettings, ProcessingRun
from db.session import get_session
from phase2_documents.reader import DETECTION_MODEL, RECOGNITION_MODELS, read_document
from phase3_extraction import llm
from phase3_extraction.extractor import extract
from phase3_extraction.schemas import Extraction, ExtractedDocument
from phase4_matching.matcher import EMBEDDING_MODEL, align_items, find_links, name_similarity, normalize_id
from phase5_verification import nli
from phase5_verification.engine import verify
from phase5_verification.models import RULES_VERSION, DocumentRecord
from phase5_verification.models import Finding as CheckResult  # db.models also has a Finding
from phase6_rag.rag import index_document

log = logging.getLogger(__name__)

MODEL_VERSIONS = {
    "rules": RULES_VERSION,
    "ocr": f"{DETECTION_MODEL}+{'/'.join(sorted(RECOGNITION_MODELS.values()))}",
    "llm": llm.MODEL,
    "embeddings": EMBEDDING_MODEL,
    "nli": nli.NLI_MODEL,
}
CONFIG_VERSION = ";".join(f"{k}={v}" for k, v in MODEL_VERSIONS.items())
USABLE_LINKS = ("proposed", "confirmed")
RETRY_PAUSES = (10, 30, 0)  # seconds to wait after attempts 1 and 2; 3 attempts in total


class TemporaryFailure(Exception):
    """A failure that may succeed later (e.g. the LLM was restarting): Reprocess will retry."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def cache_key(doc: Document) -> str:
    settings = json.dumps(doc.overrides or {}, sort_keys=True)
    return hashlib.sha256(f"{doc.sha256}|{settings}|{CONFIG_VERSION}".encode()).hexdigest()


@contextmanager
def _stage(session: Session, doc: Document, run: ProcessingRun, name: str):
    doc.stage = name
    session.commit()
    start = time.perf_counter()
    try:
        yield
    except Exception as error:
        run.stages = [*run.stages, {"stage": name, "seconds": round(time.perf_counter() - start, 2), "ok": False,
                                    "error": f"{type(error).__name__}: {error}"[:500]}]
        raise
    run.stages = [*run.stages, {"stage": name, "seconds": round(time.perf_counter() - start, 2), "ok": True}]


def _friendly(stage: str | None, error: Exception) -> str:
    text = f"{type(error).__name__}: {error}"
    if isinstance(error, TemporaryFailure) or "connect" in text.lower() and "11434" in text:
        return ("The local AI model (Ollama) could not be reached after 3 attempts. "
                "Start Ollama, then press Reprocess.")
    if isinstance(error, FileNotFoundError):
        return "The uploaded file is missing from storage. Upload it again."
    return f"Processing failed while {stage or 'starting'}: {text}"[:1000]


def process_document(document_id: int) -> None:
    lock = redis.lock(f"veritas:process:{document_id}", timeout=JOB_TIMEOUT)
    if not lock.acquire(blocking=False):
        log.info("Document %s is already being processed; skipping this duplicate job", document_id)
        return
    try:
        affected = _process(document_id)
    finally:
        try:
            lock.release()
        except LockError:
            pass
    for invoice_id in affected:
        notify_review_needed(invoice_id)


def _process(document_id: int) -> set[int]:
    with get_session() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            return set()
        run = ProcessingRun(document_id=doc.id, status="running", config_version=CONFIG_VERSION, stages=[])
        session.add(run)
        doc.status, doc.error, doc.processing_started_at, doc.progress = "processing", None, _now(), {}
        session.commit()
        try:
            original = session.scalar(select(Document).where(
                Document.organization_id == doc.organization_id, Document.sha256 == doc.sha256,
                Document.id != doc.id, Document.duplicate_of_id.is_(None)).order_by(Document.id)) if doc.sha256 else None
            if original is not None:
                doc.duplicate_of_id, doc.status, doc.stage = original.id, "duplicate", "done"
                doc.doc_type, doc.number, doc.is_current = original.doc_type, original.number, False
                run.status, run.finished_at = "duplicate", _now()
                session.commit()
                return set()

            key = cache_key(doc)
            if doc.cache_key == key and doc.extraction and doc.text is not None:
                run.stages = [*run.stages, {"stage": "reading+extracting", "skipped": True,
                                            "reason": "same file, settings and model versions as last time"}]
            else:
                _read_and_extract(session, doc, run)
                doc.cache_key = key

            with _stage(session, doc, run, "identifying"):
                _identify(session, doc)
            with _stage(session, doc, run, "matching"):
                affected = _rematch(session, doc)
            with _stage(session, doc, run, "verifying"):
                for invoice_id in sorted(affected):
                    verify_invoice(session, invoice_id)

            doc.status, doc.stage, doc.processed_at = "processed", "done", _now()
            run.status, run.finished_at = "done", _now()
            session.commit()
            return affected
        except Exception as error:
            stage = doc.stage
            session.rollback()
            doc = session.get(Document, document_id)
            run = session.get(ProcessingRun, run.id)
            message = _friendly(stage, error)
            doc.status, doc.error = "failed", message
            run.status, run.error, run.finished_at = "failed", message, _now()
            session.commit()
            log.exception("Document %s failed", document_id)
            return set()


def _read_and_extract(session: Session, doc: Document, run: ProcessingRun) -> None:
    overrides = doc.overrides or {}

    def page_done(page: int, pages: int) -> None:
        doc.progress = {"page": page, "pages": pages}
        session.commit()

    with _stage(session, doc, run, "reading"):
        content = read_document(doc.file_path, language=overrides.get("language") or None, on_page=page_done)
    with _stage(session, doc, run, "extracting"):
        # The local LLM may be restarting: retry a couple of times before giving up.
        for attempt, pause in enumerate(RETRY_PAUSES, start=1):
            try:
                result = extract(content.text, overrides=overrides, pages=[p.text for p in content.pages])
                break
            except (httpx.ConnectError, ConnectionError) as error:
                if attempt == len(RETRY_PAUSES):
                    raise TemporaryFailure(str(error)) from error
                time.sleep(pause)
    doc.text = content.text
    doc.pages = [p.model_dump(exclude={"text"}) for p in content.pages]
    doc.extraction = result.model_dump(mode="json")
    doc.doc_type, doc.number, doc.language = result.data.doc_type, result.data.number, result.locale.language
    doc.progress = {"pages": len(content.pages), "items": len(result.data.line_items)}
    with _stage(session, doc, run, "indexing"):
        index_document(doc, [(p.number, p.text) for p in content.pages])


def _identify(session: Session, doc: Document) -> None:
    """Detect revisions: same identity (type + issuer + number), different file."""
    data = Extraction.model_validate(doc.extraction).data
    doc.identity_key = identity_key(data)
    if not doc.identity_key:
        return
    others = session.scalars(select(Document).where(
        Document.organization_id == doc.organization_id, Document.identity_key == doc.identity_key,
        Document.id != doc.id, Document.duplicate_of_id.is_(None))).all()
    family = sorted([doc, *others], key=lambda d: (
        Extraction.model_validate(d.extraction).data.issue_date or date.min if d.extraction else date.min,
        d.created_at or _now(), d.id))
    for member in family:
        member.supersedes_id, member.revision, member.is_current = None, 1, True
    # Only a document that states it is a revision replaces the previous one (see backend/identity.py).
    for older, newer in zip(family, family[1:]):
        if declares_revision(newer.text or ""):
            newer.supersedes_id, newer.revision = older.id, older.revision + 1
            older.is_current = False


def _data(doc: Document) -> ExtractedDocument:
    return Extraction.model_validate(doc.extraction).data


def _rematch(session: Session, doc: Document) -> set[int]:
    """Propose links for the invoices this document can affect; return invoices to verify.

    Candidates are narrowed before any expensive comparison: an invoice that cites order
    numbers is only compared with orders carrying those numbers; one without references
    only with orders from a similar supplier.
    """
    org = doc.organization_id
    current = session.scalars(select(Document).where(
        Document.organization_id == org, Document.extraction.is_not(None), Document.is_current,
        Document.duplicate_of_id.is_(None), Document.doc_type.in_(["invoice", "purchase_order"]))).all()
    invoices = {d.id: d for d in current if d.doc_type == "invoice"}
    orders = {d.id: d for d in current if d.doc_type == "purchase_order"}

    if doc.id in invoices:
        to_match = {doc.id}
    elif doc.id in orders:
        number = normalize_id(doc.number) if doc.number else None
        previously = {l.invoice_id for l in session.scalars(select(Link).where(
            or_(Link.purchase_order_id == doc.id, Link.purchase_order_id == doc.supersedes_id)))}
        to_match = {i for i, inv in invoices.items()
                    if (number and number in {normalize_id(r) for r in _data(inv).references})
                    or not _data(inv).references} | (previously & set(invoices))
    else:
        return set()

    for invoice_id in to_match:
        invoice = _data(invoices[invoice_id])
        refs = {normalize_id(r) for r in invoice.references}
        if refs:
            candidates = {k: o for k, o in orders.items() if o.number and normalize_id(o.number) in refs}
        else:
            candidates = {k: o for k, o in orders.items() if name_similarity(invoice.supplier, _data(o).supplier) >= 0.5}
        records = {str(invoice_id): invoice, **{str(k): _data(o) for k, o in candidates.items()}}
        _sync_links(session, invoice_id, find_links(records))
    session.flush()

    # Other invoices billing the same orders need their cumulative checks refreshed.
    linked_orders = {l.purchase_order_id for l in session.scalars(select(Link).where(
        Link.invoice_id.in_(to_match), Link.status.in_(USABLE_LINKS)))}
    siblings = {l.invoice_id for l in session.scalars(select(Link).where(
        Link.purchase_order_id.in_(linked_orders), Link.status.in_(USABLE_LINKS)))} if linked_orders else set()
    return (to_match | siblings) & set(invoices)


def _sync_links(session: Session, invoice_id: int, proposals) -> None:
    existing = {l.purchase_order_id: l for l in session.scalars(select(Link).where(Link.invoice_id == invoice_id))}
    decided = {po for po, l in existing.items() if l.status in ("confirmed", "rejected") or l.method == "manual"}
    proposed = {int(p.purchase_order): p for p in proposals if int(p.purchase_order) not in decided}
    for po_id, link in existing.items():
        if po_id not in decided and po_id not in proposed:
            session.delete(link)
    for po_id, p in proposed.items():
        link = existing.get(po_id)
        if link is None:
            session.add(Link(invoice_id=invoice_id, purchase_order_id=po_id, score=p.score, reasons=p.reasons,
                             status=p.status, method=p.method))
        else:
            link.score, link.reasons, link.status, link.method = p.score, p.reasons, p.status, p.method


def record_for(session: Session, doc: Document) -> DocumentRecord:
    """The verification view of a document: corrections applied, trust information attached."""
    extraction = Extraction.model_validate(doc.extraction)
    corrections = active_corrections(session, doc.id)
    data = apply_corrections(extraction.data, corrections)
    evidence = dict(extraction.evidence)
    ungrounded = list(extraction.ungrounded)
    for c in corrections:
        evidence[c.field_path] = f"Corrected by a reviewer: {c.reason}"
        ungrounded = [u for u in ungrounded if not u.startswith(f"{c.field_path}=")]
    confidences = [p["confidence"] for p in doc.pages or [] if p.get("confidence") is not None]
    return DocumentRecord(id=doc.number or doc.filename, data=data, text=doc.text or "", evidence=evidence,
                          ungrounded=ungrounded, min_ocr_confidence=min(confidences) if confidences else None)


def _previously_billed(session: Session, invoice: Document, orders: list[Document],
                       records: dict[int, DocumentRecord]) -> dict[tuple[str, int], Decimal]:
    """Quantities of each order line already billed by EARLIER invoices (partial invoicing)."""
    billed: dict[tuple[str, int], Decimal] = {}
    own = _data(invoice)
    for po in orders:
        others = session.scalars(select(Document).join(Link, Link.invoice_id == Document.id).where(
            Link.purchase_order_id == po.id, Link.status.in_(USABLE_LINKS), Document.id != invoice.id,
            Document.is_current, Document.duplicate_of_id.is_(None))).all()
        for other in others:
            other_data = record_for(session, other).data
            earlier = ((other_data.issue_date or date.min), other.id) < ((own.issue_date or date.min), invoice.id)
            if not earlier:
                continue
            for i, j, _ in align_items(other_data.line_items, records[po.id].data.line_items):
                key = (records[po.id].id, j)
                billed[key] = billed.get(key, Decimal(0)) + other_data.line_items[i].quantity
    return billed


def _fingerprint(result: CheckResult) -> str:
    material = [result.check, result.subject, result.claim, [(e.document, e.field, e.value) for e in result.evidence]]
    return hashlib.sha256(json.dumps(material, default=str).encode()).hexdigest()


def _matching_finding(session: Session, invoice: Document) -> CheckResult:
    pending = session.scalars(select(Link).where(Link.invoice_id == invoice.id,
                                                 Link.status.in_(["ambiguous", "conflict"]))).all()
    refs = _data(invoice).references
    if any(l.status == "ambiguous" for l in pending):
        why = "Ambiguous match, review required: several orders fit this invoice. Choose the right one."
    elif pending:
        why = "The cited order exists, but its supplier or buyer differs, so it was not linked: " \
              + "; ".join(r for l in pending for r in l.reasons[1:2])
    elif refs:
        why = f"The invoice cites {', '.join(refs)}, which has not been uploaded. Upload the order to compare."
    else:
        why = "No matching purchase order was found among the uploaded documents."
    return CheckResult(check="matching_order", claim="This invoice corresponds to a known purchase order",
                       verdict="insufficient_evidence", severity="warning", kind="not_checked", explanation=why)


def verify_invoice(session: Session, invoice_id: int) -> None:
    invoice = session.get(Document, invoice_id)
    if invoice is None or not invoice.extraction or invoice.duplicate_of_id or not invoice.is_current:
        return
    links = session.scalars(select(Link).where(Link.invoice_id == invoice_id, Link.status.in_(USABLE_LINKS))).all()
    orders = [o for o in (session.get(Document, l.purchase_order_id) for l in links) if o is not None and o.extraction]
    records = {o.id: record_for(session, o) for o in orders}
    results = verify(record_for(session, invoice), [records[o.id] for o in orders],
                     _previously_billed(session, invoice, orders, records) if orders else None)
    if not orders:
        results.append(_matching_finding(session, invoice))
    _upsert_findings(session, invoice, results, related_id=orders[0].id if orders else None)
    session.commit()


def _upsert_findings(session: Session, invoice: Document, results: list[CheckResult], related_id: int | None) -> None:
    existing = {f.fingerprint: f for f in session.scalars(select(Finding).where(
        Finding.document_id == invoice.id, Finding.review_status != "superseded"))}
    fresh = {}
    for result in results:
        fresh.setdefault(_fingerprint(result), result)

    for fingerprint, finding in existing.items():
        if fingerprint in fresh:
            continue
        if finding.review_status in ("pending", "not_required"):
            session.delete(finding)  # an automatic result that no longer applies
        else:
            finding.review_status = "superseded"  # a person decided on evidence that has since changed
            finding.updated_at = _now()

    for fingerprint, r in fresh.items():
        values = dict(check=r.check, claim=r.claim, verdict=r.verdict, severity=r.severity, kind=r.kind,
                      explanation=r.explanation, evidence=[e.model_dump() for e in r.evidence], impact=r.impact,
                      currency=r.currency, subject=r.subject, related_document_id=related_id,
                      rule_version=RULES_VERSION, model_versions=MODEL_VERSIONS)
        if fingerprint in existing:
            finding = existing[fingerprint]
            for field, value in values.items():
                setattr(finding, field, value)
            finding.updated_at = _now()
        else:
            # People only need to look at problems and gaps, not at checks that passed.
            session.add(Finding(document_id=invoice.id, fingerprint=fingerprint,
                                review_status="not_required" if r.verdict == "supported" else "pending", **values))


def notify_review_needed(invoice_id: int) -> None:
    """Send NEW open problems to n8n once. Delivery is tracked per finding; failures are recorded."""
    url = os.getenv("N8N_WEBHOOK_URL")
    if not url:
        return
    with get_session() as session:
        invoice = session.get(Document, invoice_id)
        if invoice is None:
            return
        settings = session.get(OrganizationSettings, invoice.organization_id) or OrganizationSettings(
            organization_id=invoice.organization_id, alert_recipients=[], email_mode="preview",
            alert_min_severity="critical")
        severities = ["critical"] if settings.alert_min_severity == "critical" else ["critical", "warning"]
        open_findings = session.scalars(select(Finding).where(
            Finding.document_id == invoice_id, Finding.review_status == "pending",
            Finding.severity.in_(severities))).all()
        already = {d.fingerprint for d in session.scalars(select(AlertDelivery).where(
            AlertDelivery.organization_id == invoice.organization_id, AlertDelivery.kind == "finding",
            AlertDelivery.fingerprint.in_([f.fingerprint for f in open_findings])))} if open_findings else set()
        new = [f for f in open_findings if f.fingerprint and f.fingerprint not in already]
        if not new:
            return
        deliveries = [AlertDelivery(organization_id=invoice.organization_id, document_id=invoice.id, kind="finding",
                                    fingerprint=f.fingerprint, status="queued", recipients=settings.alert_recipients,
                                    summary=f.claim[:300]) for f in new]
        session.add_all(deliveries)
        session.commit()
        payload = {
            "event": "review_needed",
            "organization_id": invoice.organization_id,
            "email_mode": settings.email_mode,
            "recipients": settings.alert_recipients,
            "delivery_ids": [d.id for d in deliveries],
            "sent_at": _now().isoformat(),
            # Only a summary leaves Veritas: no document content, no files. The link needs a sign-in.
            "document": {"id": invoice.id, "number": invoice.number, "filename": invoice.filename},
            "findings": [{"id": f.id, "severity": f.severity, "claim": f.claim, "explanation": f.explanation[:400],
                          "impact": str(f.impact) if f.impact is not None else None, "currency": f.currency}
                         for f in new],
            "dashboard_url": f"{os.getenv('DASHBOARD_URL', 'http://localhost:5173')}/documents/{invoice.id}",
        }
        token = os.getenv("AUTOMATION_TOKEN", "")
        error = None
        for attempt, pause in enumerate((0, 2, 5), start=1):
            time.sleep(pause)
            try:
                httpx.post(url, json=payload, headers={"X-Veritas-Token": token}, timeout=10).raise_for_status()
                error = None
                break
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"[:500]
        for d in deliveries:
            d.attempts, d.updated_at = attempt, _now()
            d.status, d.last_error = ("failed", error) if error else ("handed_off", None)
        session.commit()
        if error:
            log.warning("n8n notification failed after %s attempts: %s", attempt, error)


def reverify(invoice_id: int) -> None:
    """Verification only (no reading, extraction or matching): after a correction or a link decision.

    Corrections to a purchase order affect every invoice linked to it, so those are re-verified too.
    """
    with get_session() as session:
        doc = session.get(Document, invoice_id)
        if doc is None:
            return
        targets = {doc.id} if doc.doc_type == "invoice" else {
            l.invoice_id for l in session.scalars(select(Link).where(Link.purchase_order_id == doc.id))}
        for target in sorted(targets):
            verify_invoice(session, target)
    for target in targets:
        notify_review_needed(target)
