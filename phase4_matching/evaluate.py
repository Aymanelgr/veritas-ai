"""Measure document matching on the synthetic dataset.

    precision = of the links we made, how many are correct?
    recall    = of the true links, how many did we find?
    F1        = harmonic mean of the two (high only if BOTH are high)

Usage:
    python -m phase4_matching.evaluate              # the saved dataset (seed 7)
    python -m phase4_matching.evaluate --seed 99    # a fresh, never-seen dataset
"""

import argparse
import time

from phase3_extraction.schemas import ExtractedDocument
from phase4_matching.matcher import find_links
from phase4_matching.synthetic import generate, load


def score(predicted: set[tuple[str, str]], truth: set[tuple[str, str]]) -> dict:
    true_positives = len(predicted & truth)
    precision = true_positives / len(predicted) if predicted else 0.0
    recall = true_positives / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1,
            "correct": true_positives, "wrong": len(predicted - truth), "missed": len(truth - predicted)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, help="evaluate on a freshly generated dataset")
    args = parser.parse_args()

    if args.seed is None:
        dataset = load()
    else:
        # A held-out dataset guards against tuning the matcher to one dataset (overfitting).
        dataset = generate(seed=args.seed)
        dataset["documents"] = {k: ExtractedDocument(**v) for k, v in dataset["documents"].items()}
    truth = {tuple(link) for link in dataset["links"]}

    for name, fuzzy in [("references only", False), ("references + fuzzy", True)]:
        start = time.time()
        links = find_links(dataset["documents"], fuzzy=fuzzy)
        # Only confident proposals count as links; "ambiguous" ones go to a person instead.
        result = score({(l.invoice, l.purchase_order) for l in links if l.status == "proposed"}, truth)
        sent_to_review = len({l.invoice for l in links if l.status == "ambiguous"})
        print(f"{name:<20} precision {result['precision']:.3f}  recall {result['recall']:.3f}  "
              f"F1 {result['f1']:.3f}  (correct {result['correct']}, wrong {result['wrong']}, "
              f"missed {result['missed']}, sent to review {sent_to_review})  {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
