"""End-to-end pipeline behavior: duplicates, revisions, ambiguity, partial invoices, manual
link decisions, corrections, idempotent reprocessing, stage records and currency gates.

Runs the real API and pipeline on the test database, with the LLM switched off so the
results are fast and deterministic (the LLM path has its own tests).
"""

import os

import pytest

os.environ["PROCESS_INLINE"] = "1"

from tests.helpers import make_user, signed_in  # noqa: E402
from tests.test_rag import postgres_running  # noqa: E402

pytestmark = pytest.mark.skipif(not postgres_running(), reason="PostgreSQL not running")


def po_text(number, items, buyer="Coastline Fabrication SARL", currency="USD", date="2026-10-01", extra=""):
    rows = "\n".join(f"{d:<28}{q:>5}   ${p:,.2f}   ${q * p:,.2f}" for d, q, p in items)
    subtotal = sum(q * p for _, q, p in items)
    return (f"PURCHASE ORDER\n\nPO Number: {number}\nDate: {date}\n" + (f"Currency: {currency}\n" if currency else "")
            + f"Buyer: {buyer}\nSupplier: Meridian Industrial Ltd\n\nItem                        Qty   Unit Price   Total\n"
            f"{rows}\n\nSubtotal: ${subtotal:,.2f}\nTax (20%): ${subtotal * 0.2:,.2f}\nTotal: ${subtotal * 1.2:,.2f}\n{extra}")


def invoice_text(number, items, refs=("PO-7001",), date="2026-10-10", currency="USD"):
    rows = "\n".join(f"{d:<28}{q:>5}   ${p:,.2f}   ${q * p:,.2f}" for d, q, p in items)
    subtotal = sum(q * p for _, q, p in items)
    refs_line = "".join(f"PO Reference: {r}\n" for r in refs)
    return (f"INVOICE\n\nInvoice Number: {number}\nInvoice Date: {date}\n" + (f"Currency: {currency}\n" if currency else "")
            + f"{refs_line}From: Meridian Industrial Ltd\nBill To: Coastline Fabrication SARL\n\n"
            f"Item                        Qty   Unit Price   Total\n{rows}\n\n"
            f"Subtotal: ${subtotal:,.2f}\nTax (20%): ${subtotal * 0.2:,.2f}\nTotal Due: ${subtotal * 1.2:,.2f}\n")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from backend import main
    from backend.routers import documents
    from db.session import reset_db

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("VERITAS_DISABLE_LLM", "1")
        reset_db()
        documents.UPLOAD_DIR = tmp_path_factory.mktemp("uploads")
        make_user("reviewer@pipeline.example", "reviewer")
        with signed_in(main.app, "reviewer@pipeline.example") as c:
            yield c


def upload(client, name, text, **overrides) -> dict:
    response = client.post("/api/documents", files={"files": (name, text.encode())}, data=overrides)
    assert response.status_code == 202, response.text
    return client.get(f"/api/documents/{response.json()[0]['id']}").json()


def problems(doc) -> set[tuple[str, str]]:
    return {(f["check"], f["kind"]) for f in doc["findings"] if f["kind"] != "ok"}


PUMPS = [("Hydraulic pump HP-200", 10, 100.0), ("Steel bolts M8", 500, 0.4)]


def test_stages_are_recorded(client):
    po = upload(client, "po-7001.txt", po_text("PO-7001", PUMPS))
    assert po["status"] == "processed" and po["stage"] == "done"
    stages = [s["stage"] for s in po["runs"][0]["stages"]]
    assert stages == ["reading", "extracting", "indexing", "identifying", "matching", "verifying"]
    assert all(s["seconds"] >= 0 for s in po["runs"][0]["stages"])


def test_duplicate_upload_is_not_processed_again(client):
    first = next(d for d in client.get("/api/documents").json() if d["number"] == "PO-7001")
    again = upload(client, "po-7001-copy.txt", po_text("PO-7001", PUMPS))
    assert again["status"] == "duplicate" and again["duplicate_of_id"] == first["id"]
    assert again["findings"] == [] and again["links"] == []


def test_partial_invoices_and_cumulative_overbilling(client):
    first = upload(client, "inv-a.txt", invoice_text("INV-A", [("Hydraulic pump HP-200", 6, 100.0)]))
    assert problems(first) == set()  # 6 of 10 pumps: fine
    second = upload(client, "inv-b.txt", invoice_text("INV-B", [("Hydraulic pump HP-200", 6, 100.0)], date="2026-10-20"))
    over = next(f for f in second["findings"] if f["check"] == "cumulative_quantity")
    assert over["kind"] == "discrepancy" and "earlier invoices billed 6" in over["explanation"]
    assert float(over["impact"]) == 200.0  # 2 pumps too many at 100


def test_reprocessing_is_idempotent_and_keeps_reviews(client):
    invoice = next(d for d in client.get("/api/documents").json() if d["number"] == "INV-B")
    before = client.get(f"/api/documents/{invoice['id']}").json()["findings"]
    over = next(f for f in before if f["check"] == "cumulative_quantity")
    client.post(f"/api/findings/{over['id']}/review", json={"decision": "approved", "note": "asked for credit"})
    for _ in range(2):
        client.post(f"/api/documents/{invoice['id']}/reprocess")
    after = client.get(f"/api/documents/{invoice['id']}").json()
    assert len(after["findings"]) == len(before)  # nothing duplicated
    kept = next(f for f in after["findings"] if f["check"] == "cumulative_quantity")
    assert kept["id"] == over["id"] and kept["review_status"] == "approved"
    assert after["runs"][0]["stages"][0].get("skipped")  # unchanged file: reading/extraction reused


def test_revision_supersedes_the_older_order(client):
    v1 = upload(client, "po-7002.txt", po_text("PO-7002", PUMPS, date="2026-10-01"))
    v2 = upload(client, "po-7002-rev.txt", po_text("PO-7002", PUMPS, date="2026-10-05",
                                                     extra="Revision 2: delivery address updated."))
    v1 = client.get(f"/api/documents/{v1['id']}").json()
    assert v2["is_current"] and not v1["is_current"]
    assert v2["supersedes_id"] == v1["id"] and v2["revision"] == 2


def test_ambiguous_match_waits_for_a_person_then_confirm(client):
    upload(client, "po-7003-a.txt", po_text("PO-7003", PUMPS, date="2026-10-01"))
    upload(client, "po-7003-b.txt", po_text("PO-7003", [("Hydraulic pump HP-200", 4, 100.0)], date="2026-10-02",
                                             buyer="Coastline Fabrication"))  # same buyer, written differently
    invoice = upload(client, "inv-c.txt", invoice_text("INV-C", [("Hydraulic pump HP-200", 4, 100.0)], refs=("PO-7003",)))
    assert {l["status"] for l in invoice["links"]} == {"ambiguous"}
    assert ("matching_order", "not_checked") in problems(invoice)
    chosen = invoice["links"][1]
    client.post(f"/api/links/{chosen['id']}/confirm", json={"note": "the revised order"})
    invoice = client.get(f"/api/documents/{invoice['id']}").json()
    statuses = {l["id"]: l["status"] for l in invoice["links"]}
    assert statuses[chosen["id"]] == "confirmed" and "rejected" in statuses.values()
    assert ("matching_order", "not_checked") not in problems(invoice)


def test_unlinked_documents_stay_unlinked_after_reprocessing(client):
    invoice = next(d for d in client.get("/api/documents").json() if d["number"] == "INV-A")
    link = client.get(f"/api/documents/{invoice['id']}").json()["links"][0]
    assert client.post(f"/api/links/{link['id']}/reject", json={"note": ""}).status_code == 422  # reason required
    client.post(f"/api/links/{link['id']}/reject", json={"note": "wrong order"})
    client.post(f"/api/documents/{invoice['id']}/reprocess")
    links = client.get(f"/api/documents/{invoice['id']}").json()["links"]
    assert [l["status"] for l in links] == ["rejected"]  # not proposed again


def test_correction_reruns_checks_and_keeps_the_original(client):
    invoice = upload(client, "inv-d.txt", invoice_text("INV-D", [("Steel bolts M8", 500, 0.4)]))
    assert problems(invoice) == set()
    response = client.post(f"/api/documents/{invoice['id']}/corrections",
                           json={"field_path": "line_items.0.quantity", "value": "450", "reason": "delivery note says 450"})
    assert response.status_code == 201 and response.json()["original_value"] == "500"
    invoice = client.get(f"/api/documents/{invoice['id']}").json()
    assert ("quantity_match", "discrepancy") in problems(invoice)
    assert invoice["extraction"]["data"]["line_items"][0]["quantity"] == "500"  # original untouched
    evidence = next(f for f in invoice["findings"] if f["check"] == "quantity_match")["evidence"][-1]
    assert "Corrected by a reviewer" in evidence["source_line"]


def test_currency_override_enables_price_checks(client):
    po = upload(client, "po-7004.txt", po_text("PO-7004", PUMPS, currency=None))
    invoice = upload(client, "inv-e.txt", invoice_text("INV-E", [("Hydraulic pump HP-200", 10, 110.0)],
                                                       refs=("PO-7004",), currency=None))
    assert ("currency_match", "not_checked") in problems(invoice)  # "$" alone: prices not compared
    for doc in (po, invoice):
        client.patch(f"/api/documents/{doc['id']}/overrides", json={"currency": "USD"})
    invoice = client.get(f"/api/documents/{invoice['id']}").json()
    assert invoice["overrides"] == {"currency": "USD"}
    assert ("unit_price_match", "discrepancy") in problems(invoice)
