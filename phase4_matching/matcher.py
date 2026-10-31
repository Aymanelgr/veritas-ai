"""Phase 4 - Document matching: decide which documents belong to the same transaction.

find_links(documents) PROPOSES links between invoices and purchase orders:
  1. Cited order numbers find candidates, which are validated (supplier, buyer, dates).
     Several candidates -> "ambiguous"; a candidate from another supplier -> "conflict".
     An invoice citing several orders is linked to each of them.
  2. Invoices without a reference: a weighted fuzzy score (supplier, buyer, line items,
     dates); the best order above LINK_THRESHOLD, unless another fits almost as well.
  An order may receive several invoices (partial invoicing).

align_items(a, b) pairs up line items that describe the same product even when
worded differently, using sentence embeddings. Phase 5 reuses it.
"""

import os
import re
from datetime import timedelta
from difflib import SequenceMatcher
from functools import cache
from typing import Literal

import numpy as np
from pydantic import BaseModel

from phase3_extraction.schemas import ExtractedDocument, LineItem

# Chosen by measurement (scripts/evaluate_languages.py, phase4_matching/evaluate.py): the multilingual
# model matches English<->French item names (8/8 vs 4/8) and Arabic (11/12 vs 10/12); on English-only
# benchmarks it misses 0-2 of 150 links that the English model finds (never a wrong link).
# Set EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 for English-only use; then run
# python scripts/reindex.py to rebuild the search passages.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
ITEM_MATCH_THRESHOLD = 0.6  # cosine similarity above which two item descriptions are "the same"
LINK_THRESHOLD = 0.8  # fuzzy score needed to link an invoice to a PO
MAX_INVOICE_DELAY = timedelta(days=120)
LEGAL_SUFFIXES = {"sarl", "ltd", "inc", "gmbh", "co", "llc", "sa", "plc", "corp"}

WEIGHTS = {"supplier": 0.25, "buyer": 0.15, "items": 0.5, "dates": 0.1}


AMBIGUITY_MARGIN = 0.05  # two fuzzy candidates closer than this are "ambiguous"


class Link(BaseModel):
    """A PROPOSED link. `score` ranks candidates; it is not a probability of being right."""

    invoice: str
    purchase_order: str
    score: float
    reasons: list[str]
    status: Literal["proposed", "ambiguous", "conflict"] = "proposed"
    method: Literal["reference", "fuzzy"] = "reference"

    @property
    def strength(self) -> str:
        return "strong" if self.score >= 0.9 else "medium" if self.score >= 0.75 else "weak"


@cache
def _embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


_embeddings: dict[str, np.ndarray] = {}
MAX_CACHED_EMBEDDINGS = 20_000  # ~30 MB; the cache is cleared rather than growing without limit


def embed(texts: list[str]) -> np.ndarray:
    """Unit-length embedding per text, cached so each text is encoded once."""
    missing = [t for t in dict.fromkeys(texts) if t not in _embeddings]
    if missing:
        if len(_embeddings) + len(missing) > MAX_CACHED_EMBEDDINGS:
            _embeddings.clear()
        vectors = _embedding_model().encode(missing, normalize_embeddings=True)
        _embeddings.update(zip(missing, vectors))
    return np.array([_embeddings[t] if t in _embeddings else embed([t])[0] for t in texts])


def _code(item: LineItem) -> str | None:
    return re.sub(r"[\s\-_/.]", "", item.code).upper() if item.code else None


def align_items(a: list[LineItem], b: list[LineItem]) -> list[tuple[int, int, float]]:
    """Pair items of `a` with items of `b`: [(index_in_a, index_in_b, similarity)].

    Exact product codes are matched first (similarity 1.0). Only items without a code,
    or whose code appears on one side only, are then paired by meaning. Two items with
    DIFFERENT codes are never paired, however similar their descriptions sound.
    """
    if not a or not b:
        return []
    pairs, used_a, used_b = [], set(), set()
    codes_b: dict[str, list[int]] = {}
    for j, item in enumerate(b):
        if code := _code(item):
            codes_b.setdefault(code, []).append(j)
    for i, item in enumerate(a):
        if (code := _code(item)) and codes_b.get(code):
            j = codes_b[code].pop(0)
            pairs.append((i, j, 1.0))
            used_a.add(i)
            used_b.add(j)

    rest_a = [i for i in range(len(a)) if i not in used_a]
    rest_b = [j for j in range(len(b)) if j not in used_b]
    if not rest_a or not rest_b:
        return pairs
    # Vectors are unit length, so the dot product IS the cosine similarity.
    sims = embed([a[i].description for i in rest_a]) @ embed([b[j].description for j in rest_b]).T
    for x, i in enumerate(rest_a):
        for y, j in enumerate(rest_b):
            if _code(a[i]) and _code(b[j]) and _code(a[i]) != _code(b[j]):
                sims[x, y] = -1  # both coded, different codes: different products
    # Greedy: take the most similar remaining pair until similarity drops too low.
    for flat in np.argsort(-sims, axis=None):
        x, y = divmod(int(flat), sims.shape[1])
        if sims[x, y] < ITEM_MATCH_THRESHOLD:
            break
        i, j = rest_a[x], rest_b[y]
        if i not in used_a and j not in used_b:
            pairs.append((i, j, float(sims[x, y])))
            used_a.add(i)
            used_b.add(j)
    return pairs


def normalize_name(name: str) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in LEGAL_SUFFIXES)


def name_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    a, b = normalize_name(a), normalize_name(b)
    # "kestrel office" is a short form of "kestrel office solutions".
    if a.startswith(b) or b.startswith(a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def score_pair(invoice: ExtractedDocument, po: ExtractedDocument) -> tuple[float, list[str]]:
    signals = {
        "supplier": name_similarity(invoice.supplier, po.supplier),
        "buyer": name_similarity(invoice.buyer, po.buyer),
    }
    # Hard constraints: a transaction cannot have two different suppliers or buyers,
    # and an invoice cannot predate its order. Matching items cannot outweigh these.
    if signals["supplier"] < 0.5:
        return 0.0, ["different supplier"]
    if invoice.buyer and po.buyer and signals["buyer"] < 0.5:
        return 0.0, ["different buyer"]

    if invoice.issue_date and po.issue_date:
        delay = invoice.issue_date - po.issue_date
        if not timedelta(0) <= delay <= MAX_INVOICE_DELAY:
            return 0.0, [f"invoice dated {delay.days} days after PO"]
        signals["dates"] = 1.0
    else:
        signals["dates"] = 0.5  # unknown: neither evidence for nor against

    aligned = align_items(invoice.line_items, po.line_items)
    signals["items"] = len(aligned) / max(len(invoice.line_items), len(po.line_items), 1)

    score = sum(WEIGHTS[k] * v for k, v in signals.items())
    reasons = [
        f"supplier similarity {signals['supplier']:.2f}",
        f"buyer similarity {signals['buyer']:.2f}",
        f"{len(aligned)} matching line items",
        "invoice dated after PO" if signals["dates"] == 1.0 else "dates unknown",
    ]
    return score, reasons


def normalize_id(identifier: str) -> str:
    """PO-2026-0147, po 2026/0147 and PO20260147 are the same identifier."""
    return re.sub(r"[\s\-_/.]", "", identifier.upper())


def validate_reference(invoice: ExtractedDocument, po: ExtractedDocument) -> tuple[bool, float, list[str]]:
    """A cited PO number only proposes a candidate; the parties and dates must agree too.

    Quantity and price differences are deliberately NOT used here: a genuine order with
    wrong quantities must still be linked, so verification can report the differences.
    """
    reasons = [f"invoice cites {po.number}"]
    strength = 0.6
    for role in ("supplier", "buyer"):
        a, b = getattr(invoice, role), getattr(po, role)
        if a and b:
            if name_similarity(a, b) < 0.5:
                return False, 0.0, reasons + [f"but the {role} differs ('{a}' vs '{b}')"]
            strength += 0.15
            reasons.append(f"same {role}")
        else:
            reasons.append(f"{role} not stated on both documents, so it could not be confirmed")
    if invoice.issue_date and po.issue_date:
        if invoice.issue_date < po.issue_date:
            reasons.append("invoice is dated BEFORE the order")
            strength -= 0.2
        else:
            strength += 0.1
            reasons.append("invoice dated after the order")
    aligned = align_items(invoice.line_items, po.line_items)
    if invoice.line_items:
        reasons.append(f"{len(aligned)} of {len(invoice.line_items)} invoiced items are on the order")
    return True, round(min(strength, 1.0), 2), reasons


def find_links(documents: dict[str, ExtractedDocument], fuzzy: bool = True) -> list[Link]:
    """Propose links between invoices and purchase orders.

    Explicit references are resolved first and VALIDATED. An invoice may cite several orders
    (each is linked), several orders may share a cited number (ambiguous: a person decides),
    and a cited order from another supplier is a conflict, not a link. Invoices without a
    reference are matched by a fuzzy score; an order may receive several invoices
    (partial invoicing). Links are proposals with a strength, never a certainty.
    """
    invoices = {k: d for k, d in documents.items() if d.doc_type == "invoice"}
    pos = {k: d for k, d in documents.items() if d.doc_type == "purchase_order"}
    by_number: dict[str, list[str]] = {}
    for key, po in pos.items():
        if po.number:
            by_number.setdefault(normalize_id(po.number), []).append(key)

    links, pending = [], []
    for inv_id, invoice in invoices.items():
        own = normalize_id(invoice.number) if invoice.number else None
        refs = [r for r in dict.fromkeys(normalize_id(r) for r in invoice.references) if r != own]
        cited = [r for r in refs if r in by_number]
        for ref in cited:
            checked = [(key, *validate_reference(invoice, pos[key])) for key in by_number[ref]]
            valid = [(key, strength, reasons) for key, ok, strength, reasons in checked if ok]
            if len(valid) > 1:
                for key, strength, reasons in valid:
                    links.append(Link(invoice=inv_id, purchase_order=key, score=strength, status="ambiguous",
                                      reasons=reasons + [f"{len(valid)} orders share the number {pos[key].number}: "
                                                         "Ambiguous match, review required"]))
            elif valid:
                key, strength, reasons = valid[0]
                links.append(Link(invoice=inv_id, purchase_order=key, score=strength, reasons=reasons))
            else:
                links += [Link(invoice=inv_id, purchase_order=key, score=0.0, status="conflict", reasons=reasons)
                          for key, _, _, reasons in checked]
        if not refs and fuzzy:
            pending.append(inv_id)
        # Cited numbers that match no uploaded order are left unlinked, never guessed.

    # Fuzzy matching. Invoices are assigned best-first, and an order only accepts another
    # invoice while it still has UNBILLED quantity for that invoice's items: genuine partial
    # invoices fit, but a second full billing of an already-billed order is never linked
    # silently; it is sent to review as possible duplicate billing.
    billed_by = {key: [] for key in pos}
    for link in links:
        if link.status == "proposed":
            billed_by[link.purchase_order].append(invoices[link.invoice])
    candidates = {}
    for inv_id in pending:
        scored = [(score, po_id, reasons) for po_id, po in pos.items()
                  for score, reasons in [score_pair(invoices[inv_id], po)] if score >= LINK_THRESHOLD]
        candidates[inv_id] = sorted(scored, reverse=True)

    for inv_id in sorted(pending, key=lambda i: -(candidates[i][0][0] if candidates[i] else 0)):
        invoice = invoices[inv_id]
        viable = [c for c in candidates[inv_id] if _has_room(invoice, pos[c[1]], billed_by[c[1]])]
        exhausted = [c for c in candidates[inv_id] if c not in viable]
        if not viable and exhausted:
            score, po_id, reasons = exhausted[0]
            links.append(Link(invoice=inv_id, purchase_order=po_id, score=round(score, 2), method="fuzzy",
                              status="ambiguous", reasons=reasons + [
                                  "this order looks already fully invoiced for these items: possible duplicate "
                                  "billing, review required"]))
        elif len(viable) > 1 and viable[0][0] - viable[1][0] < AMBIGUITY_MARGIN:
            for score, po_id, reasons in viable[:3]:
                links.append(Link(invoice=inv_id, purchase_order=po_id, score=round(score, 2), method="fuzzy",
                                  status="ambiguous", reasons=reasons + ["several orders fit almost equally well"]))
        elif viable:
            score, po_id, reasons = viable[0]
            links.append(Link(invoice=inv_id, purchase_order=po_id, score=round(score, 2), method="fuzzy",
                              reasons=["no order number on the invoice; matched by content"] + reasons))
            billed_by[po_id].append(invoice)
    return links


def _has_room(invoice: ExtractedDocument, po: ExtractedDocument, already: list[ExtractedDocument]) -> bool:
    """Does the order still have unbilled quantity for every item on this invoice?"""
    remaining = {j: item.quantity for j, item in enumerate(po.line_items)}
    for other in already:
        for i, j, _ in align_items(other.line_items, po.line_items):
            remaining[j] -= other.line_items[i].quantity
    return all(remaining[j] > 0 for _, j, _ in align_items(invoice.line_items, po.line_items))
