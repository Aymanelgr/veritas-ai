"""Audit history: a permanent record of who did what, and when."""

from sqlalchemy.orm import Session

from db.models import AuditEvent, User


def record(db: Session, user: User | None, action: str, target_type: str | None = None,
           target_id: int | None = None, organization_id: int | None = None, **details) -> None:
    """Add an audit event to the current transaction (the caller commits)."""
    db.add(AuditEvent(
        organization_id=organization_id if organization_id is not None else (user.organization_id if user else None),
        user_id=user.id if user else None, action=action, target_type=target_type, target_id=target_id,
        details={k: v for k, v in details.items() if v is not None},
    ))
