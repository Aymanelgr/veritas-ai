"""The inbox of messages delivered by n8n workflows."""

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import schemas
from backend.deps import db, require
from db.models import Notification, Organization, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def require_automation_token(x_veritas_token: str = Header("")) -> None:
    """Only callers that know the shared secret (our n8n workflows) may post notifications."""
    expected = os.getenv("AUTOMATION_TOKEN", "")
    # compare_digest takes the same time whether the first or last character differs,
    # so an attacker cannot guess the token one character at a time by timing responses.
    if not expected or not secrets.compare_digest(x_veritas_token, expected):
        raise HTTPException(401, "Invalid automation token")


@router.post("", status_code=201, dependencies=[Depends(require_automation_token)])
def create_notification(body: schemas.NotificationIn, session: Session = Depends(db)) -> schemas.NotificationOut:
    if session.get(Organization, body.organization_id) is None:
        raise HTTPException(404, "Unknown organization")
    notification = Notification(**body.model_dump())
    session.add(notification)
    session.commit()
    return schemas.NotificationOut.model_validate(notification)


@router.get("")
def list_notifications(user: User = Depends(require("viewer")),
                       session: Session = Depends(db)) -> list[schemas.NotificationOut]:
    rows = session.scalars(select(Notification).where(Notification.organization_id == user.organization_id)
                           .order_by(Notification.created_at.desc()).limit(20))
    return [schemas.NotificationOut.model_validate(n) for n in rows]


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(require("viewer")),
              session: Session = Depends(db)) -> schemas.NotificationOut:
    notification = session.get(Notification, notification_id)
    if notification is None or notification.organization_id != user.organization_id:
        raise HTTPException(404, "Notification not found")
    notification.read = True
    session.commit()
    return schemas.NotificationOut.model_validate(notification)
