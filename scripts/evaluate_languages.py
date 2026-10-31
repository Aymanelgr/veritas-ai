"""Evaluate the matching (embedding) and claim-checking (NLI) models per language.

Multilingual extraction does not make the whole pipeline multilingual: item matching,
search and claim checking use separate models, which may only work in English. This
script measures each candidate model on hand-labelled English, French and Arabic sets:

    data/eval/multilingual_items.json   pairs of item descriptions: same product or not
    data/eval/nli_claims.json           English claims (from Phase 5)
    data/eval/multilingual_claims.json  French and Arabic claims

Usage:
    python scripts/evaluate_languages.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EVAL = ROOT / "data" / "eval"
EMBEDDING_MODELS = ["sentence-transformers/all-MiniLM-L6-v2",
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]
NLI_MODELS = ["cross-encoder/nli-deberta-v3-base",
              "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"]
THRESHOLD = 0.6  # the matcher's ITEM_MATCH_THRESHOLD


def evaluate_embeddings() -> None:
    from sentence_transformers import SentenceTransformer

    pairs = json.loads((EVAL / "multilingual_items.json").read_text(encoding="utf-8"))
    print("=== Item matching: correct same/different decisions at similarity threshold 0.6 ===")
    for name in EMBEDDING_MODELS:
        model = SentenceTransformer(name)
        a = model.encode([p["a"] for p in pairs], normalize_embeddings=True)
        b = model.encode([p["b"] for p in pairs], normalize_embeddings=True)
        sims = (a * b).sum(axis=1)
        by_lang = defaultdict(list)
        for pair, sim in zip(pairs, sims):
            by_lang[pair["lang"]].append((sim >= THRESHOLD) == pair["same"])
        scores = "  ".join(f"{lang} {np.mean(ok):.0%} ({sum(ok)}/{len(ok)})" for lang, ok in by_lang.items())
        print(f"{name.split('/')[-1]:<42} {scores}")


def evaluate_nli() -> None:
    from phase5_verification import nli

    claims = json.loads((EVAL / "nli_claims.json").read_text(encoding="utf-8"))
    claims = [{**c, "lang": "en"} for c in claims]
    claims += json.loads((EVAL / "multilingual_claims.json").read_text(encoding="utf-8"))
    print("\n=== Claim checking (NLI): accuracy, and precision of 'supported' (false confirmations are the risk) ===")
    for name in NLI_MODELS:
        nli.NLI_MODEL = name
        nli._model.cache_clear()
        by_lang = defaultdict(list)
        for c in claims:
            predicted = nli.verify_claim(c["claim"], [c["premise"]])[0]
            by_lang[c["lang"]].append((predicted, c["label"]))
        parts = []
        for lang, results in by_lang.items():
            accuracy = np.mean([p == t for p, t in results])
            said_supported = [t for p, t in results if p == "supported"]
            precision = np.mean([t == "supported" for t in said_supported]) if said_supported else float("nan")
            parts.append(f"{lang} acc {accuracy:.0%} prec {precision:.0%}")
        print(f"{name.split('/')[-1]:<42} {'  '.join(parts)}")


if __name__ == "__main__":
    evaluate_embeddings()
    evaluate_nli()
