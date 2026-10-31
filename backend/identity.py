"""Document identity: which uploads are the same document, a duplicate, or a revision.

A document number is only unique within the organization that issued it: a purchase
order number belongs to the BUYER who issued it, an invoice number to the SUPPLIER. So
"PO-001 from Coastline" and "PO-001 from Atlas" are different documents.

    same file (same SHA-256)                 -> duplicate upload, not processed again
    same identity, different file content    -> a revision; the newest is current
"""

from phase3_extraction.schemas import ExtractedDocument
from phase4_matching.matcher import normalize_id, normalize_name

ISSUER = {"purchase_order": "buyer", "invoice": "supplier", "contract": "supplier"}


def identity_key(data: ExtractedDocument) -> str | None:
    if not data.number or data.doc_type not in ISSUER:
        return None
    issuer = getattr(data, ISSUER[data.doc_type])
    return f"{data.doc_type}|{normalize_name(issuer) if issuer else '?'}|{normalize_id(data.number)}"
