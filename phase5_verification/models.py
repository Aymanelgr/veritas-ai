"""Data shapes for verification results."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from phase3_extraction.schemas import ExtractedDocument

Verdict = Literal["supported", "contradicted", "insufficient_evidence"]
Severity = Literal["info", "warning", "critical"]
# What KIND of result this is, so a reading problem is never presented as an accounting problem:
#   ok                      the check ran and passed
#   discrepancy             the documents really disagree (values read with confidence)
#   possible_reading_error  a check failed, but a value involved may have been misread
#   not_checked             the check could not run (missing data, unknown currency, no order)
Kind = Literal["ok", "discrepancy", "possible_reading_error", "not_checked"]

RULES_VERSION = "2026.10-2"  # bump when a check's logic changes; stored with every finding


class DocumentRecord(BaseModel):
    """Everything verification needs about one document."""

    id: str
    data: ExtractedDocument
    text: str = ""
    evidence: dict[str, str] = Field(default_factory=dict)  # field path -> source line
    ungrounded: list[str] = Field(default_factory=list)  # "path=value" entries not found in the text
    min_ocr_confidence: float | None = None  # lowest page confidence when the document was scanned


class Evidence(BaseModel):
    document: str
    field: str
    value: str | None = None
    source_line: str | None = None


class Finding(BaseModel):
    check: str  # machine name, e.g. "quantity_match"
    claim: str  # what was tested, in plain English
    verdict: Verdict
    severity: Severity
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)
    kind: Kind = "ok"
    impact: Decimal | None = None  # money effect of the difference (positive = invoice asks for more)
    currency: str | None = None
    subject: str | None = None  # the line item or field concerned, for linking and approvals
