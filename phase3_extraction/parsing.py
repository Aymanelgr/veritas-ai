"""Small helpers that turn raw text snippets into typed values.

Thin wrappers around numbers.py and dates.py, kept for the code that only needs a value.
Pass the document's number style / date order when known; without them, ambiguous
values (like "1,234" or "03/04/2026") are skipped rather than guessed.
"""

import re
from datetime import date
from decimal import Decimal

from phase3_extraction.dates import DATE_PATTERN, dates_in
from phase3_extraction.dates import parse_date as _parse_date
from phase3_extraction.numbers import NUMBER_TOKEN, NumberStyle, numbers_in, parse_number

__all__ = ["DATE_PATTERN", "ID_PATTERN", "dates_in", "numbers_in", "parse_amount", "parse_date"]

# Document identifiers: INV-2026-0932, PO-2026-0147, BC-2026-0012, FAC/2026/118
ID_PATTERN = re.compile(r"\b[A-Z]{2,4}[-/]\d{2,4}[-/]\d{2,}(?:-[A-Z0-9]+)?\b")


def parse_date(text: str, day_first: bool | None = None) -> date | None:
    return _parse_date(text, day_first).value


def parse_amount(text: str, style: NumberStyle | None = None) -> Decimal | None:
    """The first readable number in the text (e.g. "$1,250.00" -> 1250.00)."""
    for match in NUMBER_TOKEN.finditer(text):
        value = parse_number(match.group(), style).value
        if value is not None:
            return value
    return None
