"""Alert settings (admins) and the endpoints n8n calls (shared automation token).

Veritas decides WHAT to send and records every alert in alert_deliveries, so nothing is
sent twice; n8n only delivers it (inbox, and email when an admin chose "send" and SMTP is
configured in n8n) and reports back whether delivery worked.

    email_mode  off      inbox messages only
                preview  inbox messages; emails are prepared and shown, never sent (default)
                send     emails are sent by n8n to the configured recipients
"""

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import schemas
from backend.audit import record
from backend.deps import db, require
from backend.routers.notifications import require_automation_token
from db.models import AlertDelivery, Document, Finding, Notification, Organization, OrganizationSettings, User

router = APIRouter(tags=["automation"])

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LINES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def settings_for(session: Session, organization_id: int) -> OrganizationSettings:
    found = session.get(OrganizationSettings, organization_id)
    return found or OrganizationSettings(organization_id=organization_id, alert_recipients=[], email_mode="preview",
                                         alert_min_severity="critical")


def _dashboard() -> str:
    return os.getenv("DASHBOARD_URL", "http://localhost:5173")


# ---------------------------------------------------------------- admin settings

@router.get("/api/settings/alerts")
def get_alert_settings(user: User = Depends(require("admin")), session: Session = Depends(db)) -> schemas.AlertSettings:
    s = settings_for(session, user.organization_id)
    return schemas.AlertSettings(recipients=s.alert_recipients or [], email_mode=s.email_mode,
                                 min_severity=s.alert_min_severity,
                                 webhook_configured=bool(os.getenv("N8N_WEBHOOK_URL")))


@router.put("/api/settings/alerts")
def save_alert_settings(body: schemas.AlertSettingsIn, user: User = Depends(require("admin")),
                        session: Session = Depends(db)) -> schemas.AlertSettings:
    recipients = list(dict.fromkeys(r.strip().lower() for r in body.recipients if r.strip()))
    bad = [r for r in recipients if not EMAIL.match(r)]
    if bad:
        raise HTTPException(422, f"Not an email address: {', '.join(bad)}")
    if body.email_mode == "send" and not recipients:
        raise HTTPException(422, "Add at least one recipient before turning on email sending")
    s = session.get(OrganizationSettings, user.organization_id)
    if s is None:
        s = OrganizationSettings(organization_id=user.organization_id)
        session.add(s)
    before = {"recipients": s.alert_recipients, "email_mode": s.email_mode, "min_severity": s.alert_min_severity}
    s.alert_recipients, s.email_mode, s.alert_min_severity, s.updated_at = (
        recipients, body.email_mode, body.min_severity, _now())
    record(session, user, "alert_settings_changed", "organization", user.organization_id, before=before,
           after={"recipients": recipients, "email_mode": body.email_mode, "min_severity": body.min_severity})
    session.commit()
    return get_alert_settings(user, session)


@router.get("/api/settings/alerts/deliveries")
def list_deliveries(user: User = Depends(require("admin")), session: Session = Depends(db)) -> list[schemas.DeliveryOut]:
    rows = session.scalars(select(AlertDelivery).where(AlertDelivery.organization_id == user.organization_id)
                           .order_by(AlertDelivery.id.desc()).limit(50))
    return [schemas.DeliveryOut.model_validate(d) for d in rows]


@router.post("/api/settings/alerts/test")
def send_test_alert(user: User = Depends(require("admin")), session: Session = Depends(db)) -> schemas.DeliveryOut:
    """A harmless test alert through the real path (n8n), honouring the email mode.

    In preview mode nothing is emailed: n8n only reports what it would have sent.
    Without a configured webhook the test stays local (an inbox message) and says so.
    """
    s = settings_for(session, user.organization_id)
    stamp = _now().isoformat()
    delivery = AlertDelivery(organization_id=user.organization_id, kind="test", status="queued",
                             fingerprint=hashlib.sha256(f"test|{stamp}".encode()).hexdigest(),
                             recipients=s.alert_recipients or [], summary="Test alert from Veritas AI")
    session.add(delivery)
    session.flush()
    record(session, user, "alert_test_sent", "alert", delivery.id, email_mode=s.email_mode)
    url = os.getenv("N8N_WEBHOOK_URL")
    payload = {"event": "test", "organization_id": user.organization_id, "email_mode": s.email_mode,
               "recipients": s.alert_recipients or [], "delivery_ids": [delivery.id], "sent_at": stamp,
               "document": {"id": None, "number": "TEST", "filename": "test"},
               "findings": [{"id": 0, "severity": "info", "claim": "This is a test alert",
                             "explanation": "No action needed.", "impact": None, "currency": None}],
               "dashboard_url": f"{_dashboard()}/settings"}
    if not url:
        session.add(Notification(organization_id=user.organization_id, kind="test", title="Test alert",
                                 body="N8N_WEBHOOK_URL is not set, so this test stayed inside Veritas.",
                                 link="/settings"))
        delivery.status, delivery.last_error = "skipped", "N8N_WEBHOOK_URL is not configured"
    else:
        try:
            httpx.post(url, json=payload, headers={"X-Veritas-Token": os.getenv("AUTOMATION_TOKEN", "")},
                       timeout=10).raise_for_status()
            delivery.status = "handed_off"
        except httpx.HTTPError as error:
            delivery.status, delivery.last_error = "failed", f"{type(error).__name__}: {error}"[:500]
    delivery.attempts, delivery.updated_at = 1, _now()
    session.commit()
    return schemas.DeliveryOut.model_validate(delivery)


# ---------------------------------------------------------------- called by n8n

@router.post("/api/automation/deliveries", dependencies=[Depends(require_automation_token)])
def report_delivery(body: schemas.DeliveryReportIn, session: Session = Depends(db)) -> dict:
    """n8n reports what happened to alerts it was handed: sent, preview (not sent), or failed."""
    updated = 0
    for delivery in session.scalars(select(AlertDelivery).where(AlertDelivery.id.in_(body.delivery_ids))):
        delivery.status, delivery.updated_at = body.status, _now()
        delivery.last_error = (body.error or "")[:500] or None
        updated += 1
    session.commit()
    return {"updated": updated}


def _digest(session: Session, organization: Organization, kind: str) -> dict | None:
    """Open findings of one organization, as a short message. None when there is nothing to say."""
    query = (select(Finding, Document).join(Document, Finding.document_id == Document.id)
             .where(Document.organization_id == organization.id, Finding.review_status == "pending",
                    Finding.severity.in_(["critical", "warning"])))
    if kind == "summary":  # what was found in the last 24 hours
        query = query.where(Finding.created_at >= _now() - timedelta(days=1))
    else:  # reminder: waiting for a decision for more than a day
        query = query.where(Finding.created_at < _now() - timedelta(days=1))
    rows = session.execute(query.order_by(Finding.severity, Finding.created_at)).all()
    if not rows:
        return None
    critical = sum(f.severity == "critical" for f, _ in rows)
    impact: dict[str, Decimal] = {}
    for f, _ in rows:
        if f.impact is not None and f.currency:
            impact[f.currency] = impact.get(f.currency, Decimal(0)) + abs(f.impact)
    lines = [f"- [{f.severity.upper()}] {d.number or d.filename}: {f.claim}" for f, d in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        lines.append(f"... and {len(rows) - MAX_LINES} more")
    title = (f"Reminder: {len(rows)} finding(s) still awaiting review ({critical} critical)" if kind == "reminder"
             else f"Daily summary: {len(rows)} new finding(s) to review ({critical} critical)")
    if impact:
        lines.append("Amount at stake: " + ", ".join(f"{v:,.2f} {c}" for c, v in sorted(impact.items())))
    return {"title": title, "body": "\n".join(lines), "count": len(rows), "critical": critical}


@router.get("/api/automation/digest", dependencies=[Depends(require_automation_token)])
def digest(kind: str = "reminder", session: Session = Depends(db)) -> list[dict]:
    """One message per organization with open findings; each is prepared only ONCE per day.

    Calling this twice on the same day (a retry, a manual test run) returns nothing new, so
    nobody receives the same reminder twice.
    """
    if kind not in ("reminder", "summary"):
        raise HTTPException(422, "kind must be reminder or summary")
    out = []
    day = _now().date().isoformat()
    for organization in session.scalars(select(Organization)):
        message = _digest(session, organization, kind)
        if message is None:
            continue
        fingerprint = hashlib.sha256(f"{kind}|{organization.id}|{day}".encode()).hexdigest()
        exists = session.scalar(select(AlertDelivery).where(
            AlertDelivery.organization_id == organization.id, AlertDelivery.kind == kind,
            AlertDelivery.fingerprint == fingerprint))
        if exists is not None:
            continue
        s = settings_for(session, organization.id)
        delivery = AlertDelivery(organization_id=organization.id, kind=kind, fingerprint=fingerprint,
                                 status="handed_off", attempts=1, recipients=s.alert_recipients or [],
                                 summary=message["title"][:300], updated_at=_now())
        session.add(delivery)
        session.flush()
        out.append({**message, "kind": kind, "organization_id": organization.id, "delivery_ids": [delivery.id],
                    "email_mode": s.email_mode, "recipients": s.alert_recipients or [],
                    "link": f"{_dashboard()}/reviews"})
    session.commit()
    return out
