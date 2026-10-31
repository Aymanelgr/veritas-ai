"""Measure the RAG system on questions with known answers (data/eval/rag_questions.json).

Runs against the separate `veritas_test` database, which it resets and fills
with the sample documents, so the real database is never touched.

    retrieval hit rate   the expected document is among the retrieved sources
    answer accuracy      the answer contains the expected value
    refusal accuracy     unanswerable questions get "The documents do not contain..."
    citation accuracy    share of answer clauses supported by the source they cite

Usage:
    python -m phase6_rag.evaluate
"""

import json
import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
# Must happen before db.session is imported, because it connects on import.
os.environ["DATABASE_URL"] = dotenv_values(ROOT / ".env")["DATABASE_URL"] + "_test"

from db.session import get_session, reset_db  # noqa: E402
from phase6_rag.rag import NOT_FOUND, ask, ingest_file  # noqa: E402

QUESTIONS = ROOT / "data" / "eval" / "rag_questions.json"
DOCUMENTS = ["data/samples/purchase_order.pdf", "data/samples/invoice_scan.png"]


def main() -> None:
    reset_db()
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    hits = correct = refusals_ok = 0
    answerable = [q for q in questions if q["source"]]
    citation_scores = []

    with get_session() as session:
        for path in DOCUMENTS:
            ingest_file(session, ROOT / path)

        for q in questions:
            result = ask(session, q["question"])
            if q["source"]:
                hit = q["source"] in {s.filename for s in result.sources}
                ok = any(e.lower() in result.answer.lower() for e in q["expect_any"])
                hits += hit
                correct += ok
            else:
                hit = None
                ok = NOT_FOUND in result.answer
                refusals_ok += ok
            if result.citation_accuracy is not None:
                citation_scores.append(result.citation_accuracy)

            cites = "" if result.citation_accuracy is None else f" cites {result.citation_accuracy:.0%}"
            print(f"{'OK ' if ok else 'BAD'} {q['question']}\n    -> {result.answer}{cites}")
            for check in result.checks:
                if check.verdict != "supported":
                    print(f"       unsupported citation: {check.sentence} {check.citations}")

    unanswerable = len(questions) - len(answerable)
    print(f"\nretrieval hit rate  {hits}/{len(answerable)}")
    print(f"answer accuracy     {correct}/{len(answerable)}")
    print(f"refusal accuracy    {refusals_ok}/{unanswerable}")
    if citation_scores:
        print(f"citation accuracy   {sum(citation_scores) / len(citation_scores):.0%} (mean per answer)")


if __name__ == "__main__":
    main()
