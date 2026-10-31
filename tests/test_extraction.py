from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from phase3_extraction import llm
from phase3_extraction.extractor import extract, ground, merge, repair
from phase3_extraction.parsing import parse_amount, parse_date
from phase3_extraction.rules import rule_based_extract
from phase3_extraction.schemas import ExtractedDocument

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
INVOICE_TEXT = (SAMPLES / "invoice.txt").read_text(encoding="utf-8")

# The correct answer for invoice.txt, written by hand ("gold" data).
GOLD_INVOICE = {
    "doc_type": "invoice",
    "number": "INV-2026-0932",
    "references": ["PO-2026-0147"],
    "issue_date": date(2026, 10, 18),
    "due_date": date(2026, 11, 17),
    "buyer": "Atlas Manufacturing SARL",
    "supplier": "Nordline Industrial Supplies",
    "subtotal": Decimal("4250"),
    "tax": Decimal("850"),
    "total": Decimal("5100"),
}
GOLD_QUANTITIES = [Decimal(500), Decimal(3), Decimal(20)]


def check_against_gold(data: ExtractedDocument) -> None:
    for field, expected in GOLD_INVOICE.items():
        assert getattr(data, field) == expected, field
    assert [item.quantity for item in data.line_items] == GOLD_QUANTITIES


@pytest.mark.parametrize("text, expected", [
    ("$1,250.00", Decimal("1250.00")), ("0.40", Decimal("0.40")), ("none", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["2026-11-17", "11/17/2026", "November 17, 2026"])
def test_parse_date_formats(text):
    assert parse_date(text) == date(2026, 11, 17)


def test_rules_match_gold():
    data = rule_based_extract(INVOICE_TEXT)
    check_against_gold(data)
    assert data.delivery_date == date(2026, 10, 17)


def test_grounding_flags_values_not_in_text():
    data = rule_based_extract(INVOICE_TEXT).model_copy(update={"total": Decimal("9999.00")})
    evidence, ungrounded = ground(data, INVOICE_TEXT)
    assert ungrounded == ["total=9999.00"]
    assert evidence["subtotal"] == "Subtotal: $4,250.00"


def test_line_item_evidence_comes_from_its_own_row():
    po_text = (SAMPLES / "purchase_order.txt").read_text(encoding="utf-8")
    evidence, _ = ground(rule_based_extract(po_text), po_text)
    # "20" also appears in "October 20, 2026"; the gloves row must win.
    assert evidence["line_items.2.quantity"].startswith("Safety gloves (box)")


def test_merge_fills_only_empty_fields():
    primary = ExtractedDocument(doc_type="invoice", number="A-1", total=None)
    backup = ExtractedDocument(doc_type="other", number="B-2", total=Decimal(5))
    merged, filled = merge(primary, backup)
    assert (merged.doc_type, merged.number, merged.total) == ("invoice", "A-1", Decimal(5))
    assert filled == ["total"]


def test_repair_replaces_values_not_found_in_text():
    # The kind of mistake the LLM made on real examples: "$18.50" read as 1850.
    good = rule_based_extract(INVOICE_TEXT)
    wrong_items = [good.line_items[0].model_copy(update={"unit_price": Decimal("40")}), *good.line_items[1:]]
    bad = good.model_copy(update={"total": Decimal("510000"), "line_items": wrong_items,
                                  "payment_terms": "due soon (my guess)"})
    repaired, fixed = repair(bad, good, INVOICE_TEXT)
    assert fixed == ["line_items", "payment_terms", "total"]
    assert repaired.total == Decimal("5100") and repaired.line_items[0].unit_price == Decimal("0.40")
    assert repaired.payment_terms is None  # rules found nothing: better empty than invented
    assert ground(repaired, INVOICE_TEXT)[1] == []


@pytest.mark.skipif(not llm.is_available(), reason="Ollama / qwen3:8b not running")
def test_llm_extraction_matches_gold():
    result = extract(INVOICE_TEXT)
    assert result.method == "llm"
    check_against_gold(result.data)
    assert result.ungrounded == []
