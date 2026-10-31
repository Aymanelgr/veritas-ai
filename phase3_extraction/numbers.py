"""Locale-aware number parsing.

The same characters mean different numbers in different places:
    1,234.56   English: one thousand two hundred thirty-four point five six
    1.234,56   French / German / many others: the same number
    1 234,56   French with space thousands: the same number
    1,234      1234 in English, 1.234 in French: AMBIGUOUS without context

Rules used here:
  - When both "." and "," appear, the LAST one is the decimal separator.
  - A single separator followed by 1, 2 or 4+ digits is a decimal separator.
  - A single separator followed by exactly 3 digits is ambiguous; the document's
    number style (detected from its other numbers, or set by the user) decides. If the
    style is unknown, the value is flagged as ambiguous instead of guessed.
  - "-25.00", "25.00-", "(25.00)" and "−25.00" are negative (credits).
  - Arabic-Indic digits (٠١٢…) and Arabic separators (٫ decimal, ٬ thousands) are converted.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

NumberStyle = Literal["dot_decimal", "comma_decimal"]

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_SEPARATORS = str.maketrans({"٫": ".", "٬": ",", "،": ","})
_SPACES = re.compile(r"[\s   ']")  # spaces, no-break spaces, thin spaces, Swiss apostrophe
_NOISE = re.compile(r"[^\d.,()\-−+]")  # currency symbols and letters around the number

# A number as it appears in text: optional sign or bracket, digits with separators.
NUMBER_TOKEN = re.compile(
    r"[(−\-]?\s?\d{1,3}(?:[   .,']\d{3})+(?:[.,]\d+)?\)?-?"  # with thousands separators
    r"|[(−\-]?\d+(?:[.,]\d+)?\)?-?"  # plain
)


@dataclass(frozen=True)
class ParsedNumber:
    raw: str
    value: Decimal | None  # None when the text cannot be read unambiguously
    ambiguous: bool = False
    reason: str | None = None


def normalize_digits(text: str) -> str:
    return text.translate(_DIGITS).translate(_ARABIC_SEPARATORS)


def parse_number(raw: str, style: NumberStyle | None = None) -> ParsedNumber:
    text = normalize_digits(raw).strip()
    negative = text.startswith(("-", "−", "(")) or text.endswith("-") or (text.endswith(")") and "(" in text)
    core = _NOISE.sub("", _SPACES.sub("", text)).strip("()-−+")
    if not core or not any(c.isdigit() for c in core):
        return ParsedNumber(raw, None, False, "no digits")

    dots, commas = core.count("."), core.count(",")
    if dots and commas:
        decimal_sep = "." if core.rfind(".") > core.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        if core.count(decimal_sep) > 1:
            return ParsedNumber(raw, None, True, "several decimal separators")
        integer, fraction = core.split(decimal_sep)
        if not re.fullmatch(r"\d{1,3}(?:" + re.escape(thousands_sep) + r"\d{3})*", integer):
            return ParsedNumber(raw, None, True, "irregular thousands grouping")
        number = integer.replace(thousands_sep, "") + "." + fraction
    elif dots or commas:
        sep = "." if dots else ","
        parts = core.split(sep)
        if len(parts) > 2:  # 1.234.567 or 1,234,567: only thousands separators
            if not all(len(p) == 3 for p in parts[1:]) or len(parts[0]) > 3:
                return ParsedNumber(raw, None, True, "irregular thousands grouping")
            number = "".join(parts)
        elif len(parts[1]) == 3 and len(parts[0]) <= 3:
            # "1,234" / "1.234": thousands or decimals? Only the document's style can tell.
            if style is None:
                return ParsedNumber(raw, None, True, f"'{raw.strip()}' could be thousands or decimals")
            is_decimal = (sep == "." and style == "dot_decimal") or (sep == "," and style == "comma_decimal")
            number = f"{parts[0]}.{parts[1]}" if is_decimal else parts[0] + parts[1]
        else:
            number = f"{parts[0]}.{parts[1]}"
    else:
        number = core

    try:
        value = Decimal(number)
    except InvalidOperation:
        return ParsedNumber(raw, None, True, "not a number")
    return ParsedNumber(raw, -value if negative else value)


def detect_style(text: str) -> NumberStyle | None:
    """Guess the document's number style from numbers that are NOT ambiguous."""
    text = normalize_digits(text)
    dot = len(re.findall(r"\d,\d{3}\.\d{1,2}(?!\d)", text)) + len(re.findall(r"(?<![\d.,])\d+\.\d{1,2}(?![\d.,])", text))
    comma = (len(re.findall(r"\d\.\d{3},\d{1,2}(?!\d)", text)) + len(re.findall(r"\d[   ]\d{3},\d{1,2}(?!\d)", text))
             + len(re.findall(r"(?<![\d.,])\d+,\d{1,2}(?![\d.,])", text)))
    if dot > comma:
        return "dot_decimal"
    if comma > dot:
        return "comma_decimal"
    return None


def numbers_in(text: str, style: NumberStyle | None = None) -> list[Decimal]:
    """All unambiguous numbers in a piece of text."""
    values = []
    for match in NUMBER_TOKEN.finditer(normalize_digits(text)):
        parsed = parse_number(match.group(), style)
        if parsed.value is not None:
            values.append(abs(parsed.value))  # grounding compares magnitudes; signs are checked separately
    return values
