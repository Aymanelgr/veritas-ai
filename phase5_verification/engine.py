"""Phase 5 - Verification engine for Veritas AI.

check_document(doc)                internal arithmetic of one document
compare(invoice, orders, billed)   an invoice against the purchase order(s) it is linked to
verify(invoice, orders, billed)    both, plus a search for approvals of each specific change

Every finding states a claim, a verdict (supported / contradicted / insufficient_evidence),
a severity, a kind (ok / discrepancy / possible_reading_error / not_checked), the money
impact where it can be computed, and the evidence it was based on.

Principles
  - A value that may have been misread is never reported as an accounting discrepancy.
  - A check that could not run is reported as "not checked", never as passed.
  - Missing tax is never assumed to be zero.
  - Money is only compared within ONE known currency; quantities are compared exactly.
  - Approval text found in a document makes a difference "explained, to confirm"; it never
    resolves the finding or authorizes payment. Only a person can.

Usage (from the project root):
    python -m phase5_verification.engine data/samples/invoice.txt data/samples/purchase_order.txt
"""

import argparse
import re
from decimal import Decimal

from phase2_documents.reader import read_document
from phase3_extraction.currency import money_tolerance, round_money
from phase3_extraction.extractor import extract
from phase4_matching.matcher import align_items
from phase5_verification.models import DocumentRecord, Evidence, Finding
from phase5_verification.nli import OBLIGATION, verify_claim

QUANTITY_TOLERANCE = Decimal(0)  # quantities must match exactly
LOW_OCR_CONFIDENCE = 0.90


def _ev(doc: DocumentRecord, field: str, value) -> Evidence:
    return Evidence(document=doc.id, field=field, value=None if value is None else str(value),
                    source_line=doc.evidence.get(field))


def _fmt(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return "?"
    return f"{amount:,.2f} {currency}" if currency else f"{amount:,.2f} (currency unknown)"


def _unsure(doc: DocumentRecord, *fields: str) -> str | None:
    """Why a value used by a check may be wrong, or None if it was read with confidence."""
    bad = {u.split("=")[0] for u in doc.ungrounded}
    if missing := [f for f in fields if f in bad]:
        return f"{', '.join(missing)} could not be found in the document text"
    if doc.min_ocr_confidence is not None and doc.min_ocr_confidence < LOW_OCR_CONFIDENCE:
        return f"the scan was read with low confidence ({doc.min_ocr_confidence:.0%})"
    return None


def _result(ok: bool, unsure: str | None, **kwargs) -> Finding:
    """A pass, a discrepancy, or, when a failing value may be misread, a possible reading error."""
    if ok:
        return Finding(verdict="supported", severity="info", kind="ok", **kwargs)
    if unsure:
        kwargs["explanation"] += f" This may be a reading error: {unsure}. Check the original document."
        return Finding(verdict="insufficient_evidence", severity="warning", kind="possible_reading_error", **kwargs)
    return Finding(verdict="contradicted", severity="critical", kind="discrepancy", **kwargs)


def _not_checked(check: str, claim: str, why: str, severity: str = "warning", **kwargs) -> Finding:
    return Finding(check=check, claim=claim, verdict="insufficient_evidence", severity=severity, kind="not_checked",
                   explanation=why, **kwargs)


def check_document(doc: DocumentRecord) -> list[Finding]:
    d, findings = doc.data, []
    cur, tol = d.currency, money_tolerance(d.currency)

    for i, item in enumerate(d.line_items):
        if item.unit_price is None or item.total is None:
            continue
        expected = round_money(item.quantity * item.unit_price, cur)
        ok = abs(expected - item.total) <= tol
        p = f"line_items.{i}"
        findings.append(_result(
            ok, _unsure(doc, f"{p}.quantity", f"{p}.unit_price", f"{p}.total"),
            check="line_arithmetic", subject=item.description, currency=cur,
            claim=f"'{item.description}': {item.quantity} x {item.unit_price} = {item.total}",
            explanation="Line total is correct." if ok else f"Expected {expected}, the document says {item.total}.",
            impact=None if ok else item.total - expected,
            evidence=[_ev(doc, f"{p}.total", item.total)],
        ))

    line_totals = [i.total for i in d.line_items if i.total is not None]
    if d.subtotal is not None and line_totals:
        expected = sum(line_totals, Decimal(0))
        ok = abs(expected - d.subtotal) <= tol
        findings.append(_result(
            ok, _unsure(doc, "subtotal"), check="subtotal_arithmetic", currency=cur,
            claim=f"Line totals add up to the subtotal {d.subtotal}",
            explanation="Subtotal is correct." if ok else f"The {len(line_totals)} lines add up to {expected}, not {d.subtotal}.",
            impact=None if ok else d.subtotal - expected, evidence=[_ev(doc, "subtotal", d.subtotal)],
        ))

    for i, tax in enumerate(d.taxes):
        if tax.rate is None or d.subtotal is None:
            continue
        reductions = sum((a.amount for a in d.adjustments if a.kind in ("discount", "credit")), Decimal(0))
        everything = sum((a.amount for a in d.adjustments), Decimal(0))
        # The taxable amount depends on local rules: before discounts, after discounts, or
        # after discounts and shipping. Any of the three is accepted.
        bases = (d.subtotal, d.subtotal + reductions, d.subtotal + everything)
        candidates = {round_money(base * tax.rate / 100, cur) for base in bases}
        ok = any(abs(c - tax.amount) <= tol for c in candidates)
        findings.append(_result(
            ok, _unsure(doc, f"taxes.{i}.amount"), check="tax_rate", currency=cur,
            claim=f"{tax.label}: {tax.rate}% of the taxable amount is {tax.amount}",
            explanation="Tax amount matches its rate." if ok
            else f"{tax.rate}% would be {' or '.join(sorted(map(str, candidates)))}, the document says {tax.amount}.",
            evidence=[_ev(doc, f"taxes.{i}.amount", tax.amount)],
        ))

    if d.total is not None and d.subtotal is not None:
        if d.tax is None and not d.taxes:
            findings.append(_not_checked(
                "total_arithmetic", f"Subtotal, adjustments and tax add up to the total {d.total}",
                "No tax line was found. Tax is not assumed to be zero, so the total could not be checked.",
                evidence=[_ev(doc, "total", d.total)]))
        else:
            tax = d.tax if d.tax is not None else sum((t.amount for t in d.taxes), Decimal(0))
            adjustments = sum((a.amount for a in d.adjustments), Decimal(0))
            expected = d.subtotal + adjustments + tax
            parts = [f"{d.subtotal}"] + [f"{a.amount:+}" for a in d.adjustments] + [f"+{tax}"]
            ok = abs(expected - d.total) <= tol
            findings.append(_result(
                ok, _unsure(doc, "total", "tax", "subtotal"), check="total_arithmetic", currency=cur,
                claim=f"Subtotal, adjustments and tax add up to the total {d.total}",
                explanation="Total is correct." if ok else f"{' '.join(parts)} = {expected}, not {d.total}.",
                impact=None if ok else d.total - expected,
                evidence=[_ev(doc, "total", d.total), _ev(doc, "tax", d.tax)],
            ))
    return findings


def _currency_gate(invoice: DocumentRecord, orders: list[DocumentRecord]) -> tuple[bool, list[Finding]]:
    """Money may only be compared when every document states the same, known currency."""
    inv_cur = invoice.data.currency
    order_curs = {o.data.currency for o in orders}
    if inv_cur and order_curs == {inv_cur}:
        return True, [Finding(check="currency_match", claim=f"The invoice and the order are both in {inv_cur}",
                              verdict="supported", severity="info", kind="ok", explanation=f"Both use {inv_cur}.")]
    if inv_cur and None not in order_curs:
        return False, [Finding(
            check="currency_match", claim="The invoice uses the order's currency", verdict="contradicted",
            severity="critical", kind="discrepancy",
            explanation=f"The invoice is in {inv_cur} but the order is in {', '.join(sorted(order_curs))}. "
                        "Prices and totals were NOT compared (no currency conversion).",
            evidence=[_ev(invoice, "currency", inv_cur)] + [_ev(o, "currency", o.data.currency) for o in orders])]
    unknown = [d.id for d in [invoice, *orders] if not d.data.currency]
    return False, [_not_checked(
        "currency_match", "The invoice and the order use the same currency",
        f"The currency of {', '.join(unknown)} is not stated (or not supported), so prices and totals were NOT "
        "compared. Set the currency on the document to enable these checks.")]


def compare(invoice: DocumentRecord, orders: list[DocumentRecord],
            previously_billed: dict[tuple[str, int], Decimal] | None = None) -> list[Finding]:
    """Compare an invoice with its order(s). `previously_billed` maps (order id, line index) to
    the quantity already billed by OTHER invoices, for cumulative over-billing checks."""
    inv = invoice.data
    previously_billed = previously_billed or {}
    money_ok, findings = _currency_gate(invoice, orders)
    cur = inv.currency if money_ok else None

    # All order lines together, remembering which order each came from (one invoice may cite several).
    order_lines = [(po, j, item) for po in orders for j, item in enumerate(po.data.line_items)]
    pairs = align_items(inv.line_items, [item for _, _, item in order_lines])
    matched_inv, matched_po = {i for i, _, _ in pairs}, {k for _, k, _ in pairs}

    for i, k, _ in pairs:
        a = inv.line_items[i]
        po, j, b = order_lines[k]
        name, pi, pj = b.description, f"line_items.{i}", f"line_items.{j}"
        unsure = _unsure(invoice, f"{pi}.quantity", f"{pi}.unit_price") or _unsure(po, f"{pj}.quantity", f"{pj}.unit_price")

        if a.unit and b.unit and a.unit.lower().rstrip("s.") != b.unit.lower().rstrip("s."):
            findings.append(Finding(
                check="unit_match", subject=name, claim=f"'{name}' is invoiced in the ordered unit",
                verdict="contradicted", severity="warning", kind="discrepancy",
                explanation=f"Ordered in '{b.unit}', invoiced in '{a.unit}': quantities cannot be compared directly.",
                evidence=[_ev(po, f"{pj}.description", b.description), _ev(invoice, f"{pi}.description", a.description)]))
            continue

        ok = abs(a.quantity - b.quantity) <= QUANTITY_TOLERANCE
        price = a.unit_price if a.unit_price is not None else b.unit_price
        findings.append(_result(
            ok, unsure, check="quantity_match", subject=name, currency=cur,
            claim=f"Invoiced quantity of '{name}' matches the order",
            explanation=f"Both say {b.quantity}." if ok else f"Order says {b.quantity}, invoice says {a.quantity}.",
            impact=None if ok or not money_ok or price is None else round_money((a.quantity - b.quantity) * price, cur),
            evidence=[_ev(po, f"{pj}.quantity", b.quantity), _ev(invoice, f"{pi}.quantity", a.quantity)],
        ))

        billed_before = previously_billed.get((po.id, j))
        if billed_before:
            cumulative = billed_before + a.quantity
            ok = cumulative <= b.quantity
            findings.append(_result(
                ok, unsure, check="cumulative_quantity", subject=name, currency=cur,
                claim=f"All invoices together do not bill more '{name}' than ordered",
                explanation=(f"Ordered {b.quantity}; earlier invoices billed {billed_before}, this one {a.quantity} "
                             f"(total {cumulative})."),
                impact=None if ok or not money_ok or price is None else round_money((cumulative - b.quantity) * price, cur),
                evidence=[_ev(po, f"{pj}.quantity", b.quantity), _ev(invoice, f"{pi}.quantity", a.quantity)],
            ))

        if a.unit_price is not None and b.unit_price is not None:
            if money_ok:
                ok = abs(a.unit_price - b.unit_price) <= money_tolerance(cur)
                findings.append(_result(
                    ok, unsure, check="unit_price_match", subject=name, currency=cur,
                    claim=f"Invoiced unit price of '{name}' matches the order",
                    explanation=f"Both say {b.unit_price}." if ok
                    else f"Order says {_fmt(b.unit_price, cur)}, invoice says {_fmt(a.unit_price, cur)}.",
                    impact=None if ok else round_money((a.unit_price - b.unit_price) * a.quantity, cur),
                    evidence=[_ev(po, f"{pj}.unit_price", b.unit_price), _ev(invoice, f"{pi}.unit_price", a.unit_price)],
                ))
            elif a.unit_price != b.unit_price:
                findings.append(_not_checked(
                    "unit_price_match", f"Invoiced unit price of '{name}' matches the order",
                    "Prices were not compared because the currencies differ or are unknown.",
                    severity="info", subject=name,
                    evidence=[_ev(po, f"{pj}.unit_price", b.unit_price), _ev(invoice, f"{pi}.unit_price", a.unit_price)]))

    for i, item in enumerate(inv.line_items):
        if i not in matched_inv:
            findings.append(Finding(
                check="unexpected_item", subject=item.description, claim=f"'{item.description}' was ordered",
                verdict="contradicted", severity="critical", kind="discrepancy", currency=cur,
                explanation="This invoiced item does not appear on the purchase order"
                            f"{'s' if len(orders) > 1 else ''}.",
                impact=item.total if money_ok else None,
                evidence=[_ev(invoice, f"line_items.{i}.description", item.description)],
            ))
    for k, (po, j, item) in enumerate(order_lines):
        if k not in matched_po:
            findings.append(Finding(
                check="item_not_invoiced", subject=item.description, claim=f"'{item.description}' was invoiced",
                verdict="insufficient_evidence", severity="info", kind="not_checked",
                explanation="Ordered but not on this invoice; it may be invoiced separately.",
                evidence=[_ev(po, f"line_items.{j}.description", item.description)],
            ))

    for po in orders:
        order = po.data
        if inv.issue_date and order.issue_date:
            ok = inv.issue_date >= order.issue_date
            findings.append(Finding(
                check="date_order", claim=f"The invoice was issued after order {po.id}",
                verdict="supported" if ok else "contradicted", severity="info" if ok else "warning",
                kind="ok" if ok else "discrepancy",
                explanation=f"Order {order.issue_date}, invoice {inv.issue_date}.",
                evidence=[_ev(po, "issue_date", order.issue_date), _ev(invoice, "issue_date", inv.issue_date)],
            ))
        if inv.delivery_date and order.delivery_date:
            ok = inv.delivery_date <= order.delivery_date
            findings.append(Finding(
                check="delivery_deadline", claim=f"Goods were shipped by the date required by {po.id}",
                verdict="supported" if ok else "contradicted", severity="info" if ok else "warning",
                kind="ok" if ok else "discrepancy",
                explanation=f"Required by {order.delivery_date}, shipped {inv.delivery_date}"
                            f"{'' if ok else f' ({(inv.delivery_date - order.delivery_date).days} days late)'}.",
                evidence=[_ev(po, "delivery_date", order.delivery_date),
                          _ev(invoice, "delivery_date", inv.delivery_date)],
            ))
    return findings


def _mentions(line: str, subject: str, value: str) -> bool:
    words = [w for w in re.findall(r"[^\W_]{3,}", subject.lower()) if not w.isdigit()]
    text = line.lower()
    return any(w in text for w in words) and (value.rstrip("0").rstrip(".") in text or value in text)


def explain_discrepancies(findings: list[Finding], documents: list[DocumentRecord]) -> list[Finding]:
    """Search for an approval of each SPECIFIC change (this item, this new value).

    Found approval text makes the finding a warning "explained, to confirm". It stays
    open: approval language in a document is not proof, and it never approves payment.
    """
    lines = [line.strip() for doc in documents for line in doc.text.splitlines()
             if line.strip() and not OBLIGATION.search(line)]
    for finding in findings:
        if finding.kind != "discrepancy" or finding.check not in {"quantity_match", "unit_price_match"}:
            continue
        new_value = finding.evidence[-1].value if finding.evidence else None
        if not new_value or not finding.subject:
            continue
        label = "quantity" if finding.check == "quantity_match" else "unit price"
        # Specific to THIS change: only sentences naming the item and the new value are candidates,
        # and the NLI claim names the new value (product codes in the claim would only confuse NLI).
        passages = [line for line in lines if _mentions(line, finding.subject, new_value)]
        claim = f"The buyer approved changing the {label} to {new_value}."
        verdict, confidence, passage = verify_claim(claim, passages) if passages else ("insufficient_evidence", 0, None)
        if verdict == "supported":
            finding.severity = "warning"
            finding.explanation += (f" Possible approval found: \"{passage}\" (NLI confidence {confidence:.2f}). "
                                    "A reviewer must confirm it; this does not approve payment.")
        else:
            finding.explanation += f" No approval for this specific change ({label} {new_value}) was found."
    return findings


def verify(invoice: DocumentRecord, orders: DocumentRecord | list[DocumentRecord] | None = None,
           previously_billed: dict[tuple[str, int], Decimal] | None = None) -> list[Finding]:
    if isinstance(orders, DocumentRecord):
        orders = [orders]
    orders = orders or []
    findings = check_document(invoice)
    if orders:
        for po in orders:
            findings += check_document(po)
        findings += compare(invoice, orders, previously_billed)
        findings = explain_discrepancies(findings, [invoice, *orders])
    return findings


def record_from_file(path: str) -> DocumentRecord:
    content = read_document(path)
    result = extract(content.text, pages=[p.text for p in content.pages])
    confidences = [p.confidence for p in content.pages if p.confidence is not None]
    return DocumentRecord(id=result.data.number or path, data=result.data, text=content.text,
                          evidence=result.evidence, ungrounded=result.ungrounded,
                          min_ocr_confidence=min(confidences) if confidences else None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify an invoice against its purchase order.")
    parser.add_argument("invoice")
    parser.add_argument("purchase_orders", nargs="*")
    args = parser.parse_args()

    invoice = record_from_file(args.invoice)
    orders = [record_from_file(p) for p in args.purchase_orders]
    icons = {"supported": "OK  ", "contradicted": "FAIL", "insufficient_evidence": "??  "}
    for f in sorted(verify(invoice, orders), key=lambda f: ["critical", "warning", "info"].index(f.severity)):
        impact = f"  impact {f.impact:+,.2f} {f.currency or ''}" if f.impact is not None else ""
        print(f"[{icons[f.verdict]}] {f.severity:<8} {f.kind:<22} {f.claim}{impact}\n         {f.explanation}")
        for e in f.evidence:
            if e.source_line:
                print(f"         evidence ({e.document}): {e.source_line}")


if __name__ == "__main__":
    main()
