"""End-to-end test of the MVP flow through the REST API."""

import os
from pathlib import Path

import pytest

os.environ["PROCESS_INLINE"] = "1"  # run background jobs immediately, inside the request

from tests.helpers import make_user, signed_in  # noqa: E402
from tests.test_rag import postgres_running  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
pytestmark = pytest.mark.skipif(not postgres_running(), reason="PostgreSQL not running")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from backend import main
    from backend.routers import documents
    from db.session import reset_db

    reset_db()
    documents.UPLOAD_DIR = tmp_path_factory.mktemp("uploads")
    make_user("admin@test.example", "admin")
    with signed_in(main.app, "admin@test.example") as test_client:
        yield test_client


def upload(client, name):
    with (SAMPLES / name).open("rb") as f:
        response = client.post("/api/documents", files={"files": (name, f)})
    assert response.status_code == 202
    return response.json()[0]["id"]


def test_mvp_flow(client):
    po_id = upload(client, "purchase_order.pdf")
    invoice_id = upload(client, "invoice_scan.png")  # a scan: goes through OCR

    docs = {d["id"]: d for d in client.get("/api/documents").json()}
    assert docs[po_id]["status"] == docs[invoice_id]["status"] == "processed"
    assert docs[invoice_id]["number"] == "INV-2026-0932"

    detail = client.get(f"/api/documents/{invoice_id}").json()
    [link] = detail["links"]
    assert link["document_id"] == po_id and link["relation"] == "purchase_order"
    rows = {r["description"]: r for r in detail["comparison"]["rows"]}
    pump = rows["Hydraulic pump HP-200"]
    assert (pump["ordered_quantity"], pump["invoiced_quantity"], pump["status"]) == ("2", "3", "mismatch")
    assert [r["status"] for r in rows.values()].count("match") == 2

    pending = client.get("/api/findings").json()
    [problem] = [f for f in pending if f["severity"] == "critical"]
    assert problem["check"] == "quantity_match" and "HP-200" in problem["claim"]
    assert len(problem["evidence"]) == 2

    reviewed = client.post(f"/api/findings/{problem['id']}/review",
                           json={"decision": "approved", "note": "Supplier contacted"}).json()
    assert reviewed["review_status"] == "approved" and reviewed["reviewed_at"]

    stats = client.get("/api/stats").json()
    assert stats["documents"] == 2 and stats["critical_open"] == 0 and stats["approved"] == 1

    # Undo puts the finding back in the queue, then confirm it again.
    undone = client.post(f"/api/findings/{problem['id']}/review", json={"decision": "pending"}).json()
    assert undone["review_status"] == "pending" and undone["reviewed_at"] is None
    client.post(f"/api/findings/{problem['id']}/review", json={"decision": "approved"})


def test_page_preview_is_a_png(client):
    po_id = next(d["id"] for d in client.get("/api/documents").json() if d["doc_type"] == "purchase_order")
    response = client.get(f"/api/documents/{po_id}/preview")
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert client.get(f"/api/documents/{po_id}/preview?page=9").status_code == 404


def test_reprocessing_keeps_human_reviews(client):
    invoice_id = next(d["id"] for d in client.get("/api/documents").json() if d["doc_type"] == "invoice")
    client.post(f"/api/documents/{invoice_id}/reprocess")
    findings = client.get(f"/api/documents/{invoice_id}").json()["findings"]
    assert [f["review_status"] for f in findings if f["severity"] == "critical"].count("approved") == 1


def test_notifications_require_the_automation_token(client, monkeypatch):
    monkeypatch.setenv("AUTOMATION_TOKEN", "secret-for-tests")
    message = {"organization_id": 1, "kind": "review_needed", "title": "1 issue", "body": "- pumps"}

    assert client.post("/api/notifications", json=message).status_code == 401
    assert client.post("/api/notifications", json=message,
                       headers={"X-Veritas-Token": "wrong"}).status_code == 401
    created = client.post("/api/notifications", json=message,
                          headers={"X-Veritas-Token": "secret-for-tests"})
    assert created.status_code == 201

    notification_id = created.json()["id"]
    assert client.post(f"/api/notifications/{notification_id}/read").json()["read"] is True


def test_rejects_unsupported_file(client):
    response = client.post("/api/documents", files={"files": ("data.xlsx", b"x")})
    assert response.status_code == 415


def test_unknown_document_is_404(client):
    assert client.get("/api/documents/999999").status_code == 404
