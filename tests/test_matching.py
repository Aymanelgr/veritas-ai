from datetime import date
from decimal import Decimal
from pathlib import Path

from phase3_extraction.rules import rule_based_extract
from phase3_extraction.schemas import ExtractedDocument, LineItem
from phase4_matching.evaluate import score
from phase4_matching.matcher import align_items, find_links, name_similarity, score_pair

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def doc(doc_type, number, buyer="Atlas Manufacturing SARL", supplier="Nordline Industrial Supplies",
        items=("Hydraulic pump HP-200", "Steel bolts M8"), issued=date(2026, 10, 1), refs=()):
    return ExtractedDocument(
        doc_type=doc_type, number=number, buyer=buyer, supplier=supplier, issue_date=issued,
        references=list(refs),
        line_items=[LineItem(description=d, quantity=Decimal(1)) for d in items],
    )


def test_name_similarity_ignores_legal_suffix_and_case():
    assert name_similarity("Kestrel Office Solutions Inc.", "KESTREL OFFICE") == 1.0
    assert name_similarity("Nordline Industrial Supplies", "NORDLINE IND. SUPPLIES") > 0.8
    assert name_similarity("Nordline Industrial Supplies", "Sahara Electrical Trading") < 0.5


def test_align_items_matches_reworded_descriptions():
    a = [LineItem(description=d, quantity=Decimal(1)) for d in
         ["Hydraulic pump HP-200", "Steel bolts M8", "Safety gloves (box)"]]
    b = [LineItem(description=d, quantity=Decimal(1)) for d in
         ["Box of safety gloves", "HP-200 Hydraulic Pump"]]
    pairs = {(i, j) for i, j, _ in align_items(a, b)}
    assert pairs == {(0, 1), (2, 0)}


def test_real_samples_are_linked_by_reference():
    docs = {
        name: rule_based_extract((SAMPLES / f"{name}.txt").read_text(encoding="utf-8"))
        for name in ["purchase_order", "invoice"]
    }
    # Documents are keyed by their own number, as the database will do.
    by_number = {d.number: d for d in docs.values()}
    [link] = find_links(by_number)
    assert (link.invoice, link.purchase_order) == ("INV-2026-0932", "PO-2026-0147")


def test_fuzzy_link_without_reference():
    docs = {"PO-1": doc("purchase_order", "PO-1"),
            "INV-1": doc("invoice", "INV-1", supplier="NORDLINE IND. SUPPLIES",
                         items=("HP-200 Hydraulic Pump", "M8 steel bolt"), issued=date(2026, 10, 20))}
    [link] = find_links(docs)
    assert link.purchase_order == "PO-1" and link.score > 0.9


def test_hard_constraints_block_links():
    po = doc("purchase_order", "PO-1")
    assert score_pair(doc("invoice", "I", buyer="Orion Medical Center"), po)[0] == 0
    assert score_pair(doc("invoice", "I", issued=date(2026, 9, 1)), po)[0] == 0  # before the PO
    assert score_pair(doc("invoice", "I", supplier="Kestrel Office"), po)[0] == 0


def test_invoice_citing_unknown_po_is_not_guessed():
    docs = {"PO-1": doc("purchase_order", "PO-1"),
            "INV-1": doc("invoice", "INV-1", refs=["PO-999"], issued=date(2026, 10, 20))}
    assert find_links(docs) == []


def test_score_metrics():
    result = score({("a", "1"), ("b", "2")}, {("a", "1"), ("c", "3")})
    assert (result["precision"], result["recall"]) == (0.5, 0.5)


# ---------- Validated references, ambiguity, conflicts, several orders, partial invoices ----------

def _proposed(links):
    return {(l.invoice, l.purchase_order) for l in links if l.status == "proposed"}


def test_cited_order_from_another_supplier_is_a_conflict_not_a_link():
    docs = {"PO-A": doc("purchase_order", "PO-9", supplier="Kestrel Office Solutions"),
            "INV-1": doc("invoice", "INV-1", refs=["PO-9"], issued=date(2026, 10, 20))}
    [link] = find_links(docs)
    assert link.status == "conflict" and "supplier differs" in " ".join(link.reasons)


def test_same_number_from_two_buyers_is_resolved_by_validation():
    docs = {"PO-A": doc("purchase_order", "PO-9", buyer="Atlas Manufacturing SARL"),
            "PO-B": doc("purchase_order", "PO-9", buyer="Riverside Foods Ltd"),
            "INV-1": doc("invoice", "INV-1", buyer="Riverside Foods Ltd", refs=["PO-9"], issued=date(2026, 10, 20))}
    assert _proposed(find_links(docs)) == {("INV-1", "PO-B")}


def test_two_valid_orders_with_the_same_number_are_ambiguous():
    docs = {"PO-A": doc("purchase_order", "PO-9"), "PO-B": doc("purchase_order", "PO-9"),
            "INV-1": doc("invoice", "INV-1", refs=["PO-9"], issued=date(2026, 10, 20))}
    links = find_links(docs)
    assert {l.status for l in links} == {"ambiguous"} and len(links) == 2
    assert "review required" in links[0].reasons[-1]


def test_invoice_citing_two_orders_is_linked_to_both():
    docs = {"PO-A": doc("purchase_order", "PO-1"), "PO-B": doc("purchase_order", "PO-2"),
            "INV-1": doc("invoice", "INV-1", refs=["PO-1", "PO-2"], issued=date(2026, 10, 20))}
    assert _proposed(find_links(docs)) == {("INV-1", "PO-A"), ("INV-1", "PO-B")}


def test_quantity_and_price_differences_do_not_block_a_reference_link():
    po = doc("purchase_order", "PO-1")
    invoice = doc("invoice", "INV-1", refs=["PO-1"], issued=date(2026, 10, 20))
    invoice.line_items[0].quantity = Decimal(99)  # very different, still the same order
    assert _proposed(find_links({"PO-A": po, "INV-1": invoice})) == {("INV-1", "PO-A")}


def test_several_partial_invoices_can_match_one_order():
    docs = {"PO-A": doc("purchase_order", "PO-1"),
            "INV-1": doc("invoice", "INV-1", issued=date(2026, 10, 10)),
            "INV-2": doc("invoice", "INV-2", issued=date(2026, 10, 25))}
    assert _proposed(find_links(docs)) == {("INV-1", "PO-A"), ("INV-2", "PO-A")}


def test_reference_link_strength_is_described_not_certain():
    docs = {"PO-A": doc("purchase_order", "PO-1"),
            "INV-1": doc("invoice", "INV-1", refs=["PO-1"], issued=date(2026, 10, 20))}
    [link] = find_links(docs)
    assert link.strength == "strong" and link.score < 1.01
    assert any("same supplier" in r for r in link.reasons)


def test_normalized_identifiers():
    from phase4_matching.matcher import normalize_id

    assert normalize_id("PO-2026-0147") == normalize_id("po 2026/0147") == "PO20260147"
