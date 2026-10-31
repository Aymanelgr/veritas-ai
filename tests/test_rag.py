import socket
from pathlib import Path

import pytest

from phase3_extraction import llm
from phase6_rag.rag import _claims, _linearize, chunk_text

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def postgres_running() -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", 5432)) == 0


def test_chunks_break_at_blank_lines_and_size():
    text = "A\nB\n\nC\n" + "x" * 200 + "\n" + "y" * 200
    assert chunk_text([(1, text)]) == [(1, "A\nB"), (1, "C\n" + "x" * 200), (1, "y" * 200)]


def test_claims_split_at_citations():
    answer = "2 pumps were ordered [2], and 3 were invoiced [1]. The total is $5,100.00 [1][3]."
    assert _claims(answer) == [
        ("2 pumps were ordered.", [2]),
        ("and 3 were invoiced.", [1]),
        ("The total is $5,100.00.", [1, 3]),
    ]


def test_linearize_uses_table_header():
    table = "Item                     Qty   Unit Price   Total\nHydraulic pump HP-200      2   $1,250.00    $2,500.00"
    assert _linearize(table) == ["Item: Hydraulic pump HP-200, Qty: 2, Unit Price: $1,250.00, Total: $2,500.00"]


@pytest.mark.skipif(not postgres_running(), reason="PostgreSQL not running")
def test_index_and_search():
    from db.session import get_session, reset_db
    from phase6_rag.rag import ingest_file, search

    reset_db()
    with get_session() as session:
        ingest_file(session, SAMPLES / "purchase_order.txt")
        ingest_file(session, SAMPLES / "invoice.txt")

        # Semantic: no shared keyword with the stored text "Total Due".
        top = search(session, "How much money must Atlas pay the supplier?", k=5)  # the app retrieves 5
        assert any("Total Due: $5,100.00" in c.text for c in top)

        # Exact identifier: always retrieved.
        top = search(session, "What does INV-2026-0932 say?", k=2)
        assert "INV-2026-0932" in top[0].text


@pytest.mark.skipif(not (postgres_running() and llm.is_available()), reason="needs PostgreSQL and Ollama")
def test_ask_answers_with_supported_citation():
    from db.session import get_session
    from phase6_rag.rag import NOT_FOUND, ask

    with get_session() as session:  # documents indexed by test_index_and_search
        result = ask(session, "What is the total amount due on the invoice?")
        assert "5,100" in result.answer
        assert result.citation_accuracy == 1.0
        assert NOT_FOUND in ask(session, "What is the supplier's bank account number?").answer
