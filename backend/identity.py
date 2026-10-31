"""Document identity: which uploads are the same document, a duplicate, or a revision.

A document number is only unique within the organization that issued it: a purchase
order number belongs to the BUYER who issued it, an invoice number to the SUPPLIER. So
"PO-001 from Coastline" and "PO-001 from Atlas" are different documents.

    same file (same SHA-256)                 -> duplicate upload, not processed again
    same identity, and the newer one SAYS it -> a revision; the newest is current
    is a revision ("Revision 2", "amended")
    same identity, no such statement         -> two documents sharing a number: both stay
                                                current and matching asks a person to choose

Never silently hiding an order is the safer failure: a reused number costs one review,
while a wrongly assumed revision would compare an invoice with the wrong order.
"""

import re

from phase3_extraction.schemas import ExtractedDocument
from phase4_matching.matcher import normalize_id, normalize_name

ISSUER = {"purchase_order": "buyer", "invoice": "supplier", "contract": "supplier"}


def identity_key(data: ExtractedDocument) -> str | None:
    if not data.number or data.doc_type not in ISSUER:
        return None
    issuer = getattr(data, ISSUER[data.doc_type])
    return f"{data.doc_type}|{normalize_name(issuer) if issuer else '?'}|{normalize_id(data.number)}"


# English, French and Arabic wording of "this document replaces an earlier version".
REVISION = re.compile(
    r"\b(revision|revised|rev\.?\s*\d|amended|amendment|replaces|supersedes|version\s*\d|"
    r"r[ée]vision|r[ée]vis[ée]e?|modifi[ée]e?|annule et remplace|rectificati(?:f|ve|on))\b"
    r"|(?:مراجعة|معدل|تعديل|يلغي ويحل)",
    re.IGNORECASE,
)


def declares_revision(text: str) -> bool:
    return bool(REVISION.search(text or ""))
