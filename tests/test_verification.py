from decimal import Decimal
from pathlib import Path

from phase3_extraction.extractor import extract
from phase3_extraction.schemas import Adjustment, ExtractedDocument, LineItem, TaxLine
from phase4_matching.synthetic import load
from phase5_verification.engine import check_document, verify
from phase5_verification.models import DocumentRecord
from phase5_verification.nli import verify_claim

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def record(name: str, text: str | None = None) -> DocumentRecord:
    text = text or (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")
    result = extract(text, use_llm=False)
    return DocumentRecord(id=result.data.number, data=result.data, text=text, evidence=result.evidence,
                          ungrounded=result.ungrounded)


def doc(id_, doc_type, items, currency="USD", **fields) -> DocumentRecord:
    return DocumentRecord(id=id_, data=ExtractedDocument(
        doc_type=doc_type, currency=currency, number=id_,
        line_items=[LineItem(description=d, quantity=Decimal(q), unit_price=Decimal(p), total=Decimal(q) * Decimal(p),
                             code=c) for d, q, p, c in items], **fields))


def problems(findings):
    return [f for f in findings if f.verdict == "contradicted"]


def test_arithmetic_error_is_contradicted():
    doc = DocumentRecord(id="X", data=ExtractedDocument(
        doc_type="invoice", subtotal=Decimal(100), tax=Decimal(20), total=Decimal(130),
        line_items=[LineItem(description="Widget", quantity=Decimal(2), unit_price=Decimal(50),
                             total=Decimal(100))],
    ))
    [bad] = problems(check_document(doc))
    assert bad.check == "total_arithmetic" and bad.severity == "critical"


def test_missing_tax_is_insufficient_evidence():
    doc = DocumentRecord(id="X", data=ExtractedDocument(
        doc_type="invoice", subtotal=Decimal(100), total=Decimal(120)))
    [finding] = check_document(doc)
    assert finding.verdict == "insufficient_evidence"


def test_sample_invoice_flags_only_the_pump_quantity():
    [bad] = problems(verify(record("invoice"), record("purchase_order")))
    assert bad.check == "quantity_match"
    assert "HP-200" in bad.claim and bad.severity == "critical"
    assert "No approval" in bad.explanation
    # Evidence points at the exact rows on both documents.
    assert {e.source_line.split()[-3] for e in bad.evidence} == {"2", "3"}


def test_documented_approval_explains_the_change():
    text = (SAMPLES / "invoice.txt").read_text(encoding="utf-8") + (
        "\nQuantity of pumps increased to 3 as approved by the buyer by email on 2026-10-10.\n")
    [bad] = problems(verify(record("invoice", text), record("purchase_order")))
    assert bad.severity == "warning"  # explained, but still open: a person must confirm
    assert "Possible approval found" in bad.explanation and "does not approve payment" in bad.explanation


def test_approval_of_a_different_change_does_not_count():
    text = (SAMPLES / "invoice.txt").read_text(encoding="utf-8") + (
        "\nQuantity of safety gloves increased to 30 as approved by the buyer by email on 2026-10-10.\n")
    [bad] = problems(verify(record("invoice", text), record("purchase_order")))
    assert bad.severity == "critical" and "No approval for this specific change" in bad.explanation


def test_money_impact_is_computed():
    [bad] = problems(verify(record("invoice"), record("purchase_order")))
    assert bad.impact == Decimal("1250.00") and bad.currency == "USD"  # one extra pump


def test_unknown_currency_blocks_price_comparison():
    po = doc("PO-1", "purchase_order", [("Pump", 2, "100", None)], currency=None)
    inv = doc("INV-1", "invoice", [("Pump", 2, "120", None)], currency=None)
    findings = verify(inv, po)
    gate = next(f for f in findings if f.check == "currency_match")
    assert gate.kind == "not_checked" and "NOT compared" in gate.explanation
    price = next(f for f in findings if f.check == "unit_price_match")
    assert price.kind == "not_checked"  # reported, but never as a match or a mismatch
    assert next(f for f in findings if f.check == "quantity_match").kind == "ok"  # quantities still compared


def test_different_currencies_are_a_discrepancy_and_block_prices():
    po = doc("PO-1", "purchase_order", [("Pump", 2, "100", None)], currency="EUR")
    inv = doc("INV-1", "invoice", [("Pump", 2, "100", None)], currency="MAD")
    findings = verify(inv, po)
    gate = next(f for f in findings if f.check == "currency_match")
    assert gate.verdict == "contradicted" and "MAD" in gate.explanation and "EUR" in gate.explanation
    assert not any(f.check == "unit_price_match" and f.kind != "not_checked" for f in findings)


def test_total_includes_adjustments_and_several_taxes():
    invoice = DocumentRecord(id="X", data=ExtractedDocument(
        doc_type="invoice", currency="MAD", subtotal=Decimal(1000), total=Decimal("1135.00"),
        adjustments=[Adjustment(kind="discount", label="Remise", amount=Decimal(-100)),
                     Adjustment(kind="shipping", label="Transport", amount=Decimal(50))],
        taxes=[TaxLine(label="TVA 20%", rate=Decimal(20), amount=Decimal(180)),
               TaxLine(label="Taxe locale", amount=Decimal(5))]))
    total = next(f for f in check_document(invoice) if f.check == "total_arithmetic")
    assert total.kind == "ok"  # 1000 - 100 + 50 + 180 + 5 = 1135
    rate = next(f for f in check_document(invoice) if f.check == "tax_rate")
    assert rate.kind == "ok"  # 20% of 900 (after the discount, shipping not taxed) = 180


def test_misread_value_is_a_possible_reading_error_not_a_discrepancy():
    invoice = doc("INV-1", "invoice", [("Pump", 3, "100", None)], subtotal=Decimal(250))
    invoice.ungrounded = ["subtotal=250"]
    finding = next(f for f in check_document(invoice) if f.check == "subtotal_arithmetic")
    assert finding.kind == "possible_reading_error" and finding.verdict == "insufficient_evidence"
    assert "reading error" in finding.explanation


def test_low_ocr_confidence_is_a_possible_reading_error():
    invoice = doc("INV-1", "invoice", [("Pump", 3, "100", None)], subtotal=Decimal(250))
    invoice.min_ocr_confidence = 0.7
    assert next(f for f in check_document(invoice) if f.check == "subtotal_arithmetic").kind == "possible_reading_error"


def test_product_codes_are_matched_before_descriptions():
    po = doc("PO-1", "purchase_order", [("Anchor bolt M12", 9, "1", "L001"), ("Anchor bolt M10", 5, "1", "L002")])
    inv = doc("INV-1", "invoice", [("Anchor bolt M10", 9, "1", "L001"), ("Anchor bolt M12", 5, "1", "L002")])
    # Descriptions are swapped, codes are not: matching by code finds no quantity problem.
    assert not [f for f in verify(inv, po) if f.check == "quantity_match" and f.kind != "ok"]


def test_cumulative_billing_across_partial_invoices():
    po = doc("PO-1", "purchase_order", [("Pump", 10, "100", None)])
    second = doc("INV-2", "invoice", [("Pump", 6, "100", None)])
    findings = verify(second, po, previously_billed={("PO-1", 0): Decimal(6)})
    over = next(f for f in findings if f.check == "cumulative_quantity")
    assert over.kind == "discrepancy" and over.impact == Decimal("200.00")  # 2 pumps too many
    assert "earlier invoices billed 6" in over.explanation


def test_invoice_citing_two_orders_is_compared_with_both():
    po1 = doc("PO-1", "purchase_order", [("Pump", 2, "100", None)])
    po2 = doc("PO-2", "purchase_order", [("Valve", 4, "25", None)])
    inv = doc("INV-1", "invoice", [("Pump", 2, "100", None), ("Valve", 4, "25", None)])
    findings = verify(inv, [po1, po2])
    assert not [f for f in findings if f.kind in ("discrepancy", "possible_reading_error")]
    assert {f.check for f in findings if f.kind == "ok"} >= {"quantity_match", "unit_price_match"}


def test_obligations_are_not_evidence_of_facts():
    rule = "Any change in quantity or price must be approved in writing by the buyer before shipment."
    assert verify_claim("The buyer approved a change to the order.", [rule])[0] == "insufficient_evidence"


def test_clean_synthetic_invoices_raise_no_false_alarms():
    dataset = load()
    po_for = dict(dataset["links"])
    clean = [inv for inv, issues in dataset["issues"].items() if not issues and inv in po_for][:30]
    for inv_id in clean:
        findings = verify(DocumentRecord(id=inv_id, data=dataset["documents"][inv_id]),
                          DocumentRecord(id=po_for[inv_id], data=dataset["documents"][po_for[inv_id]]))
        assert problems(findings) == [], inv_id
