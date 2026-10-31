"""Shapes of API requests and responses. FastAPI validates and documents them automatically."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # build directly from SQLAlchemy objects


class DocumentOut(ORM):
    id: int
    filename: str
    status: str  # uploaded | processing | processed | failed | duplicate
    error: str | None
    doc_type: str | None
    number: str | None
    language: str | None = None
    created_at: datetime
    open_findings: int = 0
    stage: str | None = None  # reading | extracting | indexing | identifying | matching | verifying | done
    progress: dict = {}
    overrides: dict = {}
    duplicate_of_id: int | None = None
    supersedes_id: int | None = None
    revision: int = 1
    is_current: bool = True


class LinkOut(BaseModel):
    id: int
    document_id: int
    filename: str
    number: str | None
    relation: Literal["purchase_order", "invoice"]
    score: float
    strength: Literal["strong", "medium", "weak"]
    reasons: list[str]
    status: str  # proposed | ambiguous | conflict | confirmed | rejected
    method: str  # reference | fuzzy | manual
    note: str | None = None
    decided_at: datetime | None = None


class LinkDecisionIn(BaseModel):
    note: str | None = None


class LinkDecisionOut(BaseModel):
    id: int
    status: str


class LinkCreateIn(BaseModel):
    invoice_id: int
    purchase_order_id: int
    note: str


class CorrectionIn(BaseModel):
    field_path: str  # e.g. "total", "currency", "line_items.3.quantity"
    value: str | int | float | list[str] | None  # a list for "references"
    reason: str


class CorrectionOut(ORM):
    id: int
    field_path: str
    original_value: object | None
    new_value: object | None
    reason: str
    user_id: int | None
    active: bool
    created_at: datetime


class OverridesIn(BaseModel):
    doc_type: Literal["auto", "invoice", "purchase_order", "contract", "other"] | None = None
    language: Literal["auto", "en", "fr", "ar"] | None = None
    currency: Literal["auto", "MAD", "EUR", "USD"] | None = None
    day_first: bool | None = None


class ProcessingRunOut(ORM):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    stages: list
    error: str | None


class FindingOut(ORM):
    id: int
    document_id: int
    related_document_id: int | None
    check: str
    claim: str
    verdict: str
    severity: str
    explanation: str
    evidence: list[dict]
    review_status: str
    reviewer_note: str | None
    reviewed_at: datetime | None
    kind: str = "discrepancy"
    impact: Decimal | None = None
    currency: str | None = None
    subject: str | None = None
    attachments: list = []
    rule_version: str | None = None
    document_filename: str | None = None


class ComparisonRow(BaseModel):
    description: str
    ordered_quantity: Decimal | None = None
    invoiced_quantity: Decimal | None = None
    ordered_price: Decimal | None = None
    invoiced_price: Decimal | None = None
    # match | mismatch | not_invoiced (ordered only) | unexpected (invoiced only)
    status: Literal["match", "mismatch", "not_invoiced", "unexpected"]


class Comparison(BaseModel):
    """An invoice's line items side by side with those of its purchase order(s)."""

    purchase_order_id: int
    purchase_order_number: str | None
    rows: list[ComparisonRow]
    ordered_total: Decimal | None
    invoiced_total: Decimal | None
    currency: str | None = None
    money_comparable: bool = True  # False when currencies differ or are unknown


class DocumentDetail(DocumentOut):
    text: str | None
    pages: list | None
    extraction: dict | None
    # The extracted data with reviewers' corrections applied: what verification actually uses.
    effective: dict | None = None
    links: list[LinkOut]
    findings: list[FindingOut]
    comparison: Comparison | None = None
    corrections: list[CorrectionOut] = []
    runs: list[ProcessingRunOut] = []


class ReviewIn(BaseModel):
    # approved = the issue is real ("confirmed"; NOT approval of the invoice for payment),
    # rejected = false alarm, resolved = the issue was fixed (e.g. a credit note), pending = undo
    decision: Literal["approved", "rejected", "resolved", "pending"]
    note: str | None = None


class AttachmentIn(BaseModel):
    text: str  # a note or a description of supporting evidence (e.g. "email from buyer, 10 Oct")


class AskIn(BaseModel):
    question: str
    document_ids: list[int] | None = None  # limit the search to these documents
    conversation_id: int | None = None  # continue a saved conversation (None starts a new one)


class ConversationOut(ORM):
    id: int
    title: str
    document_ids: list[int] = []
    created_at: datetime
    updated_at: datetime | None = None


class ConversationTurn(BaseModel):
    question: str
    answer: dict
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[ConversationTurn] = []


class SimulationChange(BaseModel):
    document_id: int
    field_path: str
    value: str | int | float | None


class SimulateIn(BaseModel):
    changes: list[SimulationChange]


class AlertSettings(BaseModel):
    recipients: list[str]
    email_mode: Literal["off", "preview", "send"]
    min_severity: Literal["critical", "warning"]
    webhook_configured: bool = False


class AlertSettingsIn(BaseModel):
    recipients: list[str] = []
    email_mode: Literal["off", "preview", "send"] = "preview"
    min_severity: Literal["critical", "warning"] = "critical"


class DeliveryOut(ORM):
    id: int
    kind: str
    status: str
    attempts: int
    recipients: list = []
    summary: str | None = None
    last_error: str | None = None
    document_id: int | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DeliveryReportIn(BaseModel):
    delivery_ids: list[int]
    status: Literal["sent", "preview", "failed", "skipped"]
    error: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    active: bool
    organization_id: int
    organization_name: str | None = None
    last_login_at: datetime | None = None


class UserCreateIn(BaseModel):
    email: str
    name: str
    password: str
    role: Literal["viewer", "reviewer", "admin"]


class UserUpdateIn(BaseModel):
    role: Literal["viewer", "reviewer", "admin"] | None = None
    active: bool | None = None


class AuditOut(ORM):
    id: int
    user_id: int | None
    user_email: str | None = None
    action: str
    target_type: str | None
    target_id: int | None
    details: dict
    created_at: datetime


class NotificationIn(BaseModel):
    organization_id: int
    kind: str
    title: str
    body: str
    link: str | None = None


class NotificationOut(ORM):
    id: int
    kind: str
    title: str
    body: str
    link: str | None = None
    read: bool
    created_at: datetime


class Stats(BaseModel):
    documents: int
    processing: int
    failed: int
    pending_reviews: int
    critical_open: int
    approved: int
    rejected: int
