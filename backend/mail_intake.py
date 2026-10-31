"""Optional intake of documents sent to a designated mailbox.

Off unless configured. Each email is recorded once (by its Message-ID), each attachment goes
through exactly the same checks and limits as an upload, and an attachment whose content was
already received (same SHA-256) is not stored again. Sender, subject, date and attachment
identity are kept in email_intake and in the audit history.

Email content is untrusted: nothing in the email body is acted on; only attachments are imported.
"""

import email
import email.policy
import hashlib
import imaplib
import io
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.audit import record
from backend.uploads import MAX_FILES_PER_UPLOAD, RejectedUpload
from db.models import Document, EmailIntake, User


@dataclass
class IntakeConfig:
    organization_id: int
    uploader: User | None
    allowed_senders: set[str] = field(default_factory=set)  # empty = any sender
    apply: bool = False  # False = dry run: report what would happen, change nothing


def parse(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)


def _message_id(msg: EmailMessage, attachments: list[tuple[str, bytes]]) -> str:
    if msg["Message-ID"]:
        return str(msg["Message-ID"]).strip()[:500]
    # No Message-ID: identify the email by what it contains, so a re-read is still recognized.
    material = f"{msg['From']}|{msg['Date']}|{msg['Subject']}|" + "|".join(
        hashlib.sha256(data).hexdigest() for _, data in attachments)
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


def _received(msg: EmailMessage) -> datetime | None:
    try:
        when = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError):
        return None
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def import_message(session: Session, msg: EmailMessage, config: IntakeConfig) -> dict:
    """Import one email's attachments. Returns a report; writes only when config.apply is True."""
    from backend.jobs import enqueue_processing
    from backend.routers.documents import store_file

    attachments = [(Path(part.get_filename() or "attachment").name, part.get_payload(decode=True) or b"")
                   for part in msg.iter_attachments()]
    message_id = _message_id(msg, attachments)
    sender = parseaddr(str(msg["From"] or ""))[1].lower()
    report = {"message_id": message_id, "sender": sender, "subject": str(msg["Subject"] or ""),
              "received_at": (_received(msg) or datetime.now(timezone.utc)).isoformat(), "attachments": []}

    if session.scalar(select(EmailIntake).where(EmailIntake.organization_id == config.organization_id,
                                                EmailIntake.message_id == message_id)):
        return {**report, "status": "already_imported"}
    if config.allowed_senders and sender not in config.allowed_senders:
        status = "rejected"
        report["reason"] = f"sender {sender or '(none)'} is not on the allowed list"
    elif not attachments:
        status = "no_attachments"
    else:
        status = "imported"
        for name, data in attachments[:MAX_FILES_PER_UPLOAD]:
            sha256 = hashlib.sha256(data).hexdigest()
            entry = {"filename": name, "sha256": sha256, "size": len(data)}
            existing = session.scalar(select(Document).where(Document.organization_id == config.organization_id,
                                                             Document.sha256 == sha256).order_by(Document.id))
            if existing is not None:
                entry.update(status="duplicate", document_id=existing.id)
            elif not config.apply:
                entry["status"] = "would_import"
            else:
                try:
                    doc = store_file(session, config.uploader, config.organization_id, name, io.BytesIO(data),
                                     source={"source": "email", "message_id": message_id, "sender": sender,
                                             "subject": report["subject"][:200]})
                    enqueue_processing(doc.id)
                    entry.update(status="imported", document_id=doc.id)
                except RejectedUpload as error:
                    entry.update(status="rejected", reason=str(error))
            report["attachments"].append(entry)
        for name, data in attachments[MAX_FILES_PER_UPLOAD:]:
            report["attachments"].append({"filename": name, "sha256": hashlib.sha256(data).hexdigest(),
                                          "status": "rejected", "reason": f"more than {MAX_FILES_PER_UPLOAD} attachments"})
    report["status"] = status
    if config.apply:
        intake = EmailIntake(organization_id=config.organization_id, message_id=message_id, sender=sender,
                             subject=report["subject"], received_at=_received(msg),
                             attachments=report["attachments"], status=status)
        session.add(intake)
        session.flush()
        record(session, config.uploader, "email_received", "email", intake.id, organization_id=config.organization_id,
               sender=sender, subject=report["subject"][:200], status=status,
               attachments=[{k: a.get(k) for k in ("filename", "sha256", "status", "document_id")}
                            for a in report["attachments"]])
        session.commit()
    return report


def from_directory(folder: Path) -> list[EmailMessage]:
    """.eml files from a folder: for trying the intake safely, without connecting to any mailbox."""
    return [parse(path.read_bytes()) for path in sorted(folder.glob("*.eml"))]


MAX_EMAILS_PER_RUN = 50


def from_imap() -> list[EmailMessage]:
    """Recent emails from the configured mailbox, opened READ-ONLY: the mailbox is never changed.

    Emails already imported are recognized by their Message-ID, so reading the same days again
    is harmless, and an email whose import failed is simply tried again on the next run.
    """
    host, user, password = (os.getenv(k) for k in ("INTAKE_IMAP_HOST", "INTAKE_IMAP_USER", "INTAKE_IMAP_PASSWORD"))
    if not (host and user and password):
        raise SystemExit("Set INTAKE_IMAP_HOST, INTAKE_IMAP_USER and INTAKE_IMAP_PASSWORD in .env to read a mailbox")
    since = (datetime.now(timezone.utc) - timedelta(days=int(os.getenv("INTAKE_IMAP_SINCE_DAYS", "7"))))
    client = imaplib.IMAP4_SSL(host, int(os.getenv("INTAKE_IMAP_PORT", "993")))
    try:
        client.login(user, password)
        client.select(os.getenv("INTAKE_IMAP_FOLDER", "INBOX"), readonly=True)
        _, found = client.search(None, "SINCE", since.strftime("%d-%b-%Y"))
        messages = []
        for number in found[0].split()[-MAX_EMAILS_PER_RUN:]:
            _, parts = client.fetch(number, "(BODY.PEEK[])")  # PEEK: does not mark the email as read
            messages.append(parse(parts[0][1]))
        return messages
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
