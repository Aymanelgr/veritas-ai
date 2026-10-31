"""Natural Language Inference: does a passage support, contradict, or say nothing about a claim?

The model reads (premise, hypothesis) pairs and outputs probabilities for
contradiction / entailment / neutral, which map to our three verdicts.
"""

import os
import re
from functools import cache

from phase5_verification.models import Verdict

# Chosen by measurement (scripts/evaluate_languages.py): on hand-labelled claims the multilingual
# mDeBERTa scores English 92% / French 83% / Arabic 100%, with 100% precision on "supported" in all
# three; the English-only deberta-v3-base scores 92% / 67% / 50% and falsely confirmed Arabic claims.
NLI_MODEL = os.getenv("NLI_MODEL", "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")
THRESHOLD = 0.5

# Sentences stating an obligation describe what SHOULD happen, not what DID happen.
# Small NLI models confuse the two ("changes must be approved" -> "a change was
# approved"), so obligation sentences are never used as evidence of a fact.
OBLIGATION = re.compile(r"\b(must|shall|should|required|is to be|are to be|needs? to)\b", re.I)


@cache
def _model():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(NLI_MODEL)


def verify_claim(claim: str, passages: list[str]) -> tuple[Verdict, float, str | None]:
    """Return (verdict, confidence, best passage) for a claim against candidate passages."""
    passages = [p for p in passages if p.strip() and not OBLIGATION.search(p)]
    if not passages:
        return "insufficient_evidence", 0.0, None

    model = _model()
    labels = {name: index for index, name in model.config.id2label.items()}
    probs = model.predict([(p, claim) for p in passages], apply_softmax=True)

    entail = probs[:, labels["entailment"]]
    contra = probs[:, labels["contradiction"]]
    if entail.max() >= THRESHOLD:
        best = int(entail.argmax())
        return "supported", float(entail[best]), passages[best]
    if contra.max() >= THRESHOLD:
        best = int(contra.argmax())
        return "contradicted", float(contra[best]), passages[best]
    return "insufficient_evidence", float(1 - max(entail.max(), contra.max())), None
