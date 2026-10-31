"""Date parsing for English, French and Arabic documents.

    2026-10-03          ISO: always year-month-day, never ambiguous
    03/10/2026          3 October (day first: France, Morocco, UK) or March 10 (month first: US)?
    13/10/2026          unambiguous: there is no month 13, so the day comes first
    3 octobre 2026      French month name
    October 3, 2026     English month name
    3 أكتوبر 2026        Arabic month name (Gulf/Levant and Moroccan spellings)

When "03/10/2026" cannot be resolved (no locale hint, no other date in the document
proves the order), the date is flagged as ambiguous instead of guessed.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from phase3_extraction.numbers import normalize_digits

MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # French (accents are removed before lookup)
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "janv": 1, "fevr": 2, "avr": 4, "juil": 7,
    # Arabic: Gulf/Egyptian, Moroccan, and Levantine names
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5, "ماي": 5, "يونيو": 6,
    "يوليو": 7, "يوليوز": 7, "أغسطس": 8, "اغسطس": 8, "غشت": 8, "سبتمبر": 9, "شتنبر": 9,
    "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "نونبر": 11, "ديسمبر": 12, "دجنبر": 12,
    "كانون الثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5, "حزيران": 6, "تموز": 7,
    "آب": 8, "أيلول": 9, "تشرين الأول": 10, "تشرين الثاني": 11, "كانون الأول": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


_MONTH_WORD = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b"  # ISO
    r"|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}\b"  # numeric with 4-digit year
    rf"|\b\d{{1,2}}(?:er)?\.?\s+(?:{_MONTH_WORD})\.?,?\s+\d{{4}}"  # 3 octobre 2026 / 1er mai 2026
    rf"|(?:{_MONTH_WORD})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}",  # October 3, 2026
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedDate:
    raw: str
    value: date | None
    ambiguous: bool = False
    reason: str | None = None


def _safe(raw: str, y: int, m: int, d: int) -> ParsedDate:
    try:
        return ParsedDate(raw, date(y, m, d))
    except ValueError:
        return ParsedDate(raw, None, False, "not a real date")


def parse_date(raw: str, day_first: bool | None = None) -> ParsedDate:
    text = _strip_accents(normalize_digits(raw)).strip().lower()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        return _safe(raw, int(m[1]), int(m[2]), int(m[3]))

    if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text):
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if a > 12 and b <= 12:
            return _safe(raw, year, b, a)  # 13/10/2026: day first
        if b > 12 and a <= 12:
            return _safe(raw, year, a, b)  # 10/13/2026: month first
        if a == b:
            return _safe(raw, year, a, a)
        if day_first is None:
            return ParsedDate(raw, None, True,
                              f"'{raw.strip()}' could be {a} {_month_name(b)} or {_month_name(a)} {b}")
        return _safe(raw, year, b, a) if day_first else _safe(raw, year, a, b)

    words = re.findall(r"\d+|[^\W\d_]+(?:\s[^\W\d_]+)?", text)
    numbers = [int(w) for w in re.findall(r"\d+", text)]
    month = next((MONTHS[w] for w in _candidates(text) if w in MONTHS), None)
    if month and len(numbers) >= 2 and words:
        day, year = (numbers[0], numbers[1]) if numbers[1] > 31 else (numbers[1], numbers[0])
        return _safe(raw, year, month, day)
    return ParsedDate(raw, None, False, "not a date")


def _candidates(text: str) -> list[str]:
    tokens = re.findall(r"[^\W\d_]+", text)
    pairs = [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]  # two-word Levantine month names first
    return pairs + [t.rstrip(".") for t in tokens]


def _month_name(month: int) -> str:
    return date(2000, month, 1).strftime("%B")


def detect_day_first(text: str) -> bool | None:
    """Look for a numeric date that proves the order (a first number above 12, or a second)."""
    for match in re.finditer(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{4}\b", normalize_digits(text)):
        a, b = int(match[1]), int(match[2])
        if a > 12 >= b:
            return True
        if b > 12 >= a:
            return False
    return None


def dates_in(text: str, day_first: bool | None = None) -> list[date]:
    return [p.value for p in (parse_date(m.group(), day_first) for m in DATE_PATTERN.finditer(normalize_digits(text)))
            if p.value]
