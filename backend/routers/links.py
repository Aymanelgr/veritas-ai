"""Human control over matching: confirm, reject (unlink) or create links, with an audit trail.

Automatic matching only PROPOSES links. A person's decision (confirmed, rejected, or a
manual link) is never overridden by later automatic matching, and every change is
recorded in the audit history with its reason. The invoice is re-verified afterwards.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import schemas
from backend.audit import record
from backend.deps import db, owned_document, require
from backend.jobs import enqueue_verification
from db.models import Link, User

router = APIRouter(prefix="/api/links", tags=["links"])


def _owned_link(session: Session, user: User, link_id: int) -> Link:
    link = session.get(Link, link_id)
    if link is None:
        raise HTTPException(404, "Link not found")
    owned_document(session, user, link.invoice_id)  # 404 if outside the organization
    return link


def _decide(session: Session, user: User, link: Link, status: str, note: str | None) -> schemas.LinkDecisionOut:
    previous = link.status
    link.status, link.note, link.decided_by_id, link.decided_at = status, note, user.id, datetime.now(timezone.utc)
    record(session, user, f"link_{status}", "link", link.id, invoice_id=link.invoice_id,
           purchase_order_id=link.purchase_order_id, previous=previous, note=note)
    session.commit()
    enqueue_verification(link.invoice_id)
    return schemas.LinkDecisionOut(id=link.id, status=link.status)


@router.post("/{link_id}/confirm")
def confirm_link(link_id: int, body: schemas.LinkDecisionIn, user: User = Depends(require("reviewer")),
                 session: Session = Depends(db)) -> schemas.LinkDecisionOut:
    """Confirm a proposed or ambiguous link. Confirming one candidate rejects the other ambiguous ones."""
    link = _owned_link(session, user, link_id)
    if link.status == "ambiguous":
        for other in session.scalars(select(Link).where(Link.invoice_id == link.invoice_id,
                                                        Link.status == "ambiguous", Link.id != link.id)):
            other.status, other.decided_by_id, other.decided_at = "rejected", user.id, datetime.now(timezone.utc)
            other.note = f"Another order was chosen (link {link.id})"
    return _decide(session, user, link, "confirmed", body.note)


@router.post("/{link_id}/reject")
def reject_link(link_id: int, body: schemas.LinkDecisionIn, user: User = Depends(require("reviewer")),
                session: Session = Depends(db)) -> schemas.LinkDecisionOut:
    """Unlink: these documents do not belong together. Automatic matching will not propose them again."""
    if not (body.note or "").strip():
        raise HTTPException(422, "Please give a reason for unlinking")
    return _decide(session, user, _owned_link(session, user, link_id), "rejected", body.note)


@router.post("", status_code=201)
def create_link(body: schemas.LinkCreateIn, user: User = Depends(require("reviewer")),
                session: Session = Depends(db)) -> schemas.LinkDecisionOut:
    """Correct a match by linking an invoice to the right order by hand."""
    invoice = owned_document(session, user, body.invoice_id)
    order = owned_document(session, user, body.purchase_order_id)
    if invoice.doc_type != "invoice" or order.doc_type != "purchase_order":
        raise HTTPException(422, "Link an invoice to a purchase order")
    if not (body.note or "").strip():
        raise HTTPException(422, "Please say why these documents belong together")
    link = session.scalar(select(Link).where(Link.invoice_id == invoice.id, Link.purchase_order_id == order.id))
    if link is None:
        link = Link(invoice_id=invoice.id, purchase_order_id=order.id, score=1.0, method="manual",
                    reasons=[f"linked by hand: {body.note}"])
        session.add(link)
        session.flush()
    link.method = "manual"
    return _decide(session, user, link, "confirmed", body.note)
