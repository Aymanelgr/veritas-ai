"""Reviewer corrections, applied on top of the extraction (the original is never changed).

A correction targets a field path such as "total", "currency" or "line_items.3.quantity".
Verification then runs on the corrected values, and each corrected value carries the
reviewer's reason as its evidence.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Correction
from phase3_extraction.schemas import ExtractedDocument


def _set(container, path: list[str], value) -> None:
    for step in path[:-1]:
        container = container[int(step)] if isinstance(container, list) else container[step]
    last = path[-1]
    if isinstance(container, list):
        container[int(last)] = value
    else:
        container[last] = value


def get_value(data: ExtractedDocument, field_path: str):
    value = data.model_dump(mode="json")
    for step in field_path.split("."):
        value = value[int(step)] if isinstance(value, list) else value.get(step)
    return value


def active_corrections(session: Session, document_id: int) -> list[Correction]:
    return list(session.scalars(select(Correction).where(Correction.document_id == document_id,
                                                         Correction.active).order_by(Correction.id)))


def apply_corrections(data: ExtractedDocument, corrections: list[Correction]) -> ExtractedDocument:
    if not corrections:
        return data
    raw = data.model_dump(mode="json")
    for correction in corrections:
        _set(raw, correction.field_path.split("."), correction.new_value)
    return ExtractedDocument.model_validate(raw)  # validation rejects impossible values
