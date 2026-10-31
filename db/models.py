"""Database tables (SQLAlchemy ORM). Each class is one table; each attribute one column."""

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384  # size of all-MiniLM-L6-v2 vectors

# Table structure changes are made with migrations (see migrations/versions/), never by
# editing a live database by hand. After changing a model, add a migration for it.


class Base(DeclarativeBase):
    pass


class Organization(Base):
    """A company using Veritas. Users only ever see their own organization's data."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))  # viewer | reviewer | admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """A signed-in browser. Only a hash of the session token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class AuditEvent(Base):
    """Who did what, when: uploads, reviews, link changes, corrections, deletions, logins."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)  # identifies identical files
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(100))  # detected from the bytes, not the name
    overrides: Mapped[dict] = mapped_column(JSONB, default=dict)  # user-set doc_type/language/currency/day_first
    language: Mapped[str | None] = mapped_column(String(10))
    identity_key: Mapped[str | None] = mapped_column(String(400), index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    # Processing progress: stage (reading, ocr, extracting, indexing, matching, verifying, done)
    # and details such as {"page": 3, "pages": 13}.
    stage: Mapped[str | None] = mapped_column(String(30))
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    cache_key: Mapped[str | None] = mapped_column(String(64))  # file hash + settings + model versions
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # uploaded -> processing -> processed (or failed)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(String(30))
    number: Mapped[str | None] = mapped_column(String(100), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[list | None] = mapped_column(JSONB)  # how each page was read (Phase 2)
    extraction: Mapped[dict | None] = mapped_column(JSONB)  # Phase 3 result
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    """A small passage of a document plus its embedding, used for RAG search."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)  # order within the document
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(String(200))  # vectors of different models are not comparable

    document: Mapped[Document] = relationship(back_populates="chunks")


class Link(Base):
    """Two documents that belong to the same transaction (Phase 4)."""

    __tablename__ = "links"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float)  # ranking strength, not a probability
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    # proposed (automatic) | ambiguous (several candidates) | conflict (cited but parties differ)
    # | confirmed / rejected (decided by a person; automatic matching never overrides these)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    method: Mapped[str] = mapped_column(String(20), default="reference")  # reference | fuzzy | manual
    note: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """A message delivered by an n8n workflow (Phase 9), shown in the dashboard inbox."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # e.g. review_needed, reminder
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(1024))
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Finding(Base):
    """One verification result (Phase 5) plus the human review decision."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    related_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    check: Mapped[str] = mapped_column(String(50))
    claim: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    kind: Mapped[str] = mapped_column(String(30), default="discrepancy")  # ok | discrepancy | possible_reading_error | not_checked
    impact: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    subject: Mapped[str | None] = mapped_column(Text)
    # Same check + same evidence = same fingerprint: reprocessing updates the finding instead of duplicating it.
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    rule_version: Mapped[str | None] = mapped_column(String(40))
    model_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    attachments: Mapped[list] = mapped_column(JSONB, default=list)  # reviewer notes and evidence
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # pending -> approved (issue confirmed) | rejected (false alarm) | resolved (fixed) | superseded
    # (the evidence changed after a decision) | not_required (a check that passed)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcessingRun(Base):
    """One attempt to process a document: how long each stage took and what failed."""

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # running | done | failed | duplicate | skipped
    stages: Mapped[list] = mapped_column(JSONB, default=list)  # [{"stage", "seconds", "ok", "error"}]
    error: Mapped[str | None] = mapped_column(Text)
    config_version: Mapped[str | None] = mapped_column(String(400))


class Correction(Base):
    """A reviewer's fix to an extracted value. The original extraction is never overwritten."""

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    field_path: Mapped[str] = mapped_column(String(200))  # e.g. "total" or "line_items.3.quantity"
    original_value: Mapped[object | None] = mapped_column(JSONB)
    new_value: Mapped[object | None] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertDelivery(Base):
    """One alert (email or inbox message) and its delivery status; never sent twice."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("organization_id", "kind", "fingerprint", name="uq_alert_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30))  # critical | summary | reminder | test
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # queued | sent | preview | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    recipients: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    alert_recipients: Mapped[list] = mapped_column(JSONB, default=list)
    email_mode: Mapped[str] = mapped_column(String(10), default="preview")  # off | preview | send
    alert_min_severity: Mapped[str] = mapped_column(String(10), default="critical")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    """A saved assistant conversation. Private to the user who started it, inside their organization."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)  # search scope; empty = all documents
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.id")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[dict] = mapped_column(JSONB)  # the full answer: text, sources, checks, kind
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class EmailIntake(Base):
    """One email read from the intake mailbox, so the same email is never imported twice."""

    __tablename__ = "email_intake"
    __table_args__ = (UniqueConstraint("organization_id", "message_id", name="uq_email_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(500))
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # [{"filename", "sha256", "status": imported|duplicate|rejected, "document_id", "reason"}]
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20))  # imported | no_attachments | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
