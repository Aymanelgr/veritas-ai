"""Measure the verification engine.

1. Rules on the synthetic dataset: for every invoice and every discrepancy type,
   did we flag it (prediction) and was it really injected (truth)?
2. NLI on hand-labelled claims (data/eval/nli_claims.json), including traps such
   as obligations ("must be approved") that do not prove a fact.

Usage:
    python -m phase5_verification.evaluate
"""

import json
from pathlib import Path

from sklearn.metrics import classification_report, confusion_matrix

from phase4_matching.synthetic import load
from phase5_verification.engine import verify
from phase5_verification.models import DocumentRecord
from phase5_verification.nli import verify_claim

CLAIMS = Path(__file__).resolve().parent.parent / "data" / "eval" / "nli_claims.json"

# Which finding (check) reveals which injected discrepancy type.
CHECK_TO_ISSUE = {
    "quantity_match": "quantity_mismatch",
    "unit_price_match": "price_mismatch",
    "unexpected_item": "unexpected_item",
    "total_arithmetic": "arithmetic_error",
    "subtotal_arithmetic": "arithmetic_error",
    "line_arithmetic": "arithmetic_error",
}
ISSUE_TYPES = sorted(set(CHECK_TO_ISSUE.values()))


def evaluate_rules() -> None:
    dataset = load()
    docs = dataset["documents"]
    po_for = dict(dataset["links"])
    y_true, y_pred = [], []

    for inv_id, injected in dataset["issues"].items():
        invoice = DocumentRecord(id=inv_id, data=docs[inv_id])
        po = DocumentRecord(id=po_for[inv_id], data=docs[po_for[inv_id]]) if inv_id in po_for else None
        flagged = {CHECK_TO_ISSUE[f.check] for f in verify(invoice, po)
                   if f.verdict == "contradicted" and f.check in CHECK_TO_ISSUE}
        truth = {issue["type"] for issue in injected}
        # One yes/no decision per (invoice, issue type).
        for issue in ISSUE_TYPES:
            y_true.append(issue if issue in truth else "none")
            y_pred.append(issue if issue in flagged else "none")

    print("=== Rules on synthetic invoices (one row per invoice x issue type) ===")
    print(classification_report(y_true, y_pred, labels=ISSUE_TYPES, digits=3, zero_division=0))


def evaluate_nli() -> None:
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    labels = ["supported", "contradicted", "insufficient_evidence"]
    y_true = [c["label"] for c in claims]
    y_pred = [verify_claim(c["claim"], [c["premise"]])[0] for c in claims]

    print(f"=== NLI on {len(claims)} hand-labelled claims ===")
    print(classification_report(y_true, y_pred, labels=labels, digits=3, zero_division=0))
    print("Confusion matrix (rows = truth, columns = prediction):")
    print("                       " + "  ".join(f"{l[:12]:>12}" for l in labels))
    for label, row in zip(labels, confusion_matrix(y_true, y_pred, labels=labels)):
        print(f"{label:<22} " + "  ".join(f"{n:>12}" for n in row))
    for claim, predicted in zip(claims, y_pred):
        if predicted != claim["label"]:
            print(f"  WRONG: {claim['claim']!r} given {claim['premise']!r}: "
                  f"expected {claim['label']}, got {predicted}")


if __name__ == "__main__":
    evaluate_rules()
    evaluate_nli()
