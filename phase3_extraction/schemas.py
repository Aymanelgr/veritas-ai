"""Pydantic models describing the structured data we extract from a document.

Money uses Decimal, not float: float cannot store 0.10 exactly
(0.1 + 0.2 == 0.30000000000000004), which is unacceptable when comparing totals.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from phase3_extraction.language import DocumentLocale

DocType = Literal["purchase_order", "invoice", "contract", "other"]


class LineItem(BaseModel):
    # Length limits are part of the JSON schema the LLM must follow, so a model stuck in a
    # repetition loop is cut off by the schema itself instead of writing forever.
    description: str = Field(max_length=300)
    quantity: Decimal  # may be fractional (2.5 kg) or negative (a returned item)
    unit_price: Decimal | None = None
    total: Decimal | None = None
    code: str | None = Field(None, max_length=60, description="Product code / SKU / line reference, e.g. L012 or HP-200")
    unit: str | None = Field(None, max_length=20, description="Unit of measure, e.g. pcs, kg, box, h")


AdjustmentKind = Literal["discount", "shipping", "credit", "other"]


class Adjustment(BaseModel):
    """An amount outside the line items. Discounts and credits are negative."""

    kind: AdjustmentKind
    label: str = Field(max_length=120)
    amount: Decimal


class TaxLine(BaseModel):
    label: str = Field(max_length=120)
    rate: Decimal | None = None  # percent, e.g. 20 for 20 %
    amount: Decimal


class ExtractedDocument(BaseModel):
    doc_type: DocType
    number: str | None = Field(
        None, max_length=100, description="This document's own identifier, e.g. PO-2026-0147 or INV-2026-0932"
    )
    references: list[str] = Field(
        default_factory=list,
        description="Identifiers of OTHER documents mentioned, e.g. the PO number printed on an invoice",
    )
    issue_date: date | None = Field(None, description="Date the document was issued")
    due_date: date | None = Field(None, description="Payment due date")
    delivery_date: date | None = Field(None, description="Required, promised or actual delivery/shipping date")
    buyer: str | None = Field(None, max_length=200, description="Company that buys / is billed")
    supplier: str | None = Field(None, max_length=200, description="Company that sells / sends the invoice")
    currency: str | None = Field(None, description="ISO 4217 code, e.g. USD, EUR, MAD; null if not stated")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)
    taxes: list[TaxLine] = Field(default_factory=list)
    tax: Decimal | None = Field(None, description="Total tax (sum of all tax lines)")
    total: Decimal | None = Field(None, description="Grand total including tax")
    payment_terms: str | None = Field(None, max_length=200, description="Short phrase, e.g. Net 30 days")


class Coverage(BaseModel):
    """How much of the document was actually understood: reported, never hidden."""

    pages: int = 0
    table_rows_found: int = 0  # rows that look like line items
    line_items_extracted: int = 0
    skipped_lines: list[str] = Field(default_factory=list)  # table-like lines that could not be read
    ignored_lines: list[str] = Field(default_factory=list)  # repeated headers, page subtotals, carried forward
    missing_fields: list[str] = Field(default_factory=list)  # important fields not found


class Extraction(BaseModel):
    """An extraction result plus the information needed to trust (or distrust) it."""

    data: ExtractedDocument
    method: Literal["llm", "rules"]
    # Fields the LLM left empty, or got wrong, that the rule-based extractor filled in.
    filled_by_rules: list[str] = Field(default_factory=list)
    # Field path (e.g. "total", "line_items.1.quantity") -> source line it was found on.
    evidence: dict[str, str] = Field(default_factory=dict)
    # Field path -> the exact text it was read from (e.g. "1 234,56"), next to the normalized value.
    raw_values: dict[str, str] = Field(default_factory=dict)
    # Values that could NOT be found in the source text: possible hallucinations.
    ungrounded: list[str] = Field(default_factory=list)
    # Values that could not be read unambiguously, in plain words (e.g. a date that may be 3 April or March 4).
    ambiguities: list[str] = Field(default_factory=list)
    locale: DocumentLocale = Field(default_factory=DocumentLocale)
    coverage: Coverage = Field(default_factory=Coverage)
    # Problems during extraction, e.g. "The LLM answer was cut off; rule-based extraction used".
    warnings: list[str] = Field(default_factory=list)
