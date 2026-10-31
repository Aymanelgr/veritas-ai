"""The review queue: list findings and record human decisions."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import insights, schemas
from backend.audit import record
from backend.deps import db, owned_finding, require
from db.models import Document, Finding, User

router = APIRouter(prefix="/api/findings", tags=["findings"])


@router.get("")
def list_findings(review_status: str | None = "pending", severity: str | None = None,
                  user: User = Depends(require("viewer")),
                  session: Session = Depends(db)) -> list[schemas.FindingOut]:
    query = (select(Finding, Document.filename).join(Document, Finding.document_id == Document.id)
             .where(Document.organization_id == user.organization_id))
    if review_status:
        query = query.where(Finding.review_status == review_status)
    if severity:
        query = query.where(Finding.severity == severity)
    order = {"critical": 0, "warning": 1, "info": 2}
    rows = session.execute(query.order_by(Finding.created_at.desc())).all()
    out = [schemas.FindingOut.model_validate(f).model_copy(update={"document_filename": name})
           for f, name in rows]
    return sorted(out, key=lambda f: order.get(f.severity, 3))


@router.post("/{finding_id}/review")
def review_finding(finding_id: int, body: schemas.ReviewIn, user: User = Depends(require("reviewer")),
                   session: Session = Depends(db)) -> schemas.FindingOut:
    finding = owned_finding(session, user, finding_id)
    if finding.review_status == "superseded":
        raise HTTPException(409, "This finding was decided on evidence that has since changed; review the current one")
    previous = finding.review_status
    finding.review_status = body.decision
    undo = body.decision == "pending"
    finding.reviewer_note = None if undo else body.note
    finding.reviewed_at = None if undo else datetime.now(timezone.utc)
    document = session.get(Document, finding.document_id)
    # A reproducible decision: exactly which evidence, file and rule/model versions were decided on.
    record(session, user, "finding_reviewed", "finding", finding.id,
           decision=body.decision, previous=previous, note=body.note, fingerprint=finding.fingerprint,
           check=finding.check, claim=finding.claim, rule_version=finding.rule_version,
           model_versions=finding.model_versions, document_id=document.id, document_sha256=document.sha256,
           document_revision=document.revision, extraction_key=document.cache_key)
    session.commit()
    return schemas.FindingOut.model_validate(finding)


@router.post("/{finding_id}/attachments")
def attach_evidence(finding_id: int, body: schemas.AttachmentIn, user: User = Depends(require("reviewer")),
                    session: Session = Depends(db)) -> schemas.FindingOut:
    """Attach a note or a description of supporting evidence (an email, a phone call, a credit note)."""
    finding = owned_finding(session, user, finding_id)
    if not body.text.strip():
        raise HTTPException(422, "The note is empty")
    entry = {"text": body.text.strip()[:2000], "by": user.email, "at": datetime.now(timezone.utc).isoformat()}
    finding.attachments = [*(finding.attachments or []), entry]
    record(session, user, "finding_evidence_attached", "finding", finding.id, text=entry["text"][:200])
    session.commit()
    return schemas.FindingOut.model_validate(finding)


@router.get("/{finding_id}/explain")
def explain_finding(finding_id: int, user: User = Depends(require("viewer")),
                    session: Session = Depends(db)) -> dict:
    """What was compared, why it was flagged, what evidence would settle it, and its history."""
    return insights.explain(session, owned_finding(session, user, finding_id))


@router.post("/{finding_id}/clarification")
def draft_clarification(finding_id: int, user: User = Depends(require("reviewer")),
                        session: Session = Depends(db)) -> dict:
    """A message to the supplier, for the reviewer to edit and send. Veritas never sends it."""
    finding = owned_finding(session, user, finding_id)
    draft = insights.clarification(session, finding, user)
    record(session, user, "clarification_drafted", "finding", finding.id, language=draft["language"])
    session.commit()
    return draft
