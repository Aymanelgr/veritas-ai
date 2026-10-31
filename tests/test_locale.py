"""Numbers, dates, currencies and languages: the cases listed in the upgrade note."""

from datetime import date
from decimal import Decimal

import pytest

from phase3_extraction.currency import detect_currency, money_tolerance, round_money
from phase3_extraction.dates import dates_in, detect_day_first, parse_date
from phase3_extraction.language import detect_languages, detect_locale
from phase3_extraction.numbers import detect_style, numbers_in, parse_number


@pytest.mark.parametrize("raw, style, expected", [
    ("1,234.56", None, "1234.56"),
    ("1 234,56", None, "1234.56"),
    ("1.234,56", None, "1234.56"),
    ("1 234,56", None, "1234.56"),  # narrow no-break space (French typography)
    ("-25.00", None, "-25.00"),
    ("(25.00)", None, "-25.00"),  # accounting notation for a credit
    ("25,00-", None, "-25.00"),
    ("−25,50", None, "-25.50"),  # Unicode minus
    ("2.5", None, "2.5"),  # fractional quantity
    ("0,75", None, "0.75"),
    ("1,234,567.89", None, "1234567.89"),
    ("1.234.567", None, "1234567"),
    ("$4,450.00", None, "4450.00"),
    ("12 500,00 DH", None, "12500.00"),
    ("١٢٣٫٤٥", None, "123.45"),  # Arabic-Indic digits and decimal separator
    ("1,234", "dot_decimal", "1234"),
    ("1,234", "comma_decimal", "1.234"),
    ("1.234", "comma_decimal", "1234"),
])
def test_number_formats(raw, style, expected):
    assert parse_number(raw, style).value == Decimal(expected)


def test_ambiguous_number_is_flagged_not_guessed():
    parsed = parse_number("1,234")
    assert parsed.value is None and parsed.ambiguous and "thousands or decimals" in parsed.reason
    assert parse_number("1,234").raw == "1,234"  # the original text is kept


def test_number_style_detection():
    assert detect_style("Total: 1,250.00  Tax: 250.00") == "dot_decimal"
    assert detect_style("Total TTC : 1 250,00  TVA : 250,00") == "comma_decimal"
    assert detect_style("Quantity 3, item 12") is None


def test_numbers_in_uses_the_style():
    assert numbers_in("Montant 1.234,56 et 12,50", "comma_decimal") == [Decimal("1234.56"), Decimal("12.50")]


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-03", date(2026, 10, 3)),
    ("13/10/2026", date(2026, 10, 13)),  # day first: no month 13
    ("10/13/2026", date(2026, 10, 13)),  # month first: no month 13
    ("3 octobre 2026", date(2026, 10, 3)),
    ("1er février 2026", date(2026, 2, 1)),
    ("October 3, 2026", date(2026, 10, 3)),
    ("3 Oct 2026", date(2026, 10, 3)),
    ("3 أكتوبر 2026", date(2026, 10, 3)),
    ("15 شتنبر 2026", date(2026, 9, 15)),  # Moroccan month name
    ("١٥/٠٩/٢٠٢٦", date(2026, 9, 15)),
])
def test_dates(raw, expected):
    assert parse_date(raw).value == expected


def test_ambiguous_date_needs_clarification():
    parsed = parse_date("03/04/2026")
    assert parsed.value is None and parsed.ambiguous
    assert "3 April" in parsed.reason and "March 4" in parsed.reason
    assert parse_date("03/04/2026", day_first=True).value == date(2026, 4, 3)
    assert parse_date("03/04/2026", day_first=False).value == date(2026, 3, 4)


def test_date_order_detected_from_other_dates():
    assert detect_day_first("Date: 25/09/2026 ... due 03/10/2026") is True
    assert detect_day_first("Date: 09/25/2026") is False
    assert dates_in("due 03/10/2026", day_first=True) == [date(2026, 10, 3)]


@pytest.mark.parametrize("text, code", [
    ("Total: 1 200,00 MAD", "MAD"),
    ("Montant : 1 200,00 DH", "MAD"),
    ("المجموع 1200 درهم", "MAD"),
    ("Total: 1.200,00 €", "EUR"),
    ("Amount: USD 1,200.00", "USD"),
    ("Total: US$1,200.00", "USD"),
    ("Currency: EUR\nTotal: $1,200.00", "EUR"),  # an explicit declaration wins
])
def test_currencies(text, code):
    assert detect_currency(text).code == code


def test_dollar_sign_alone_is_not_assumed_to_be_usd():
    result = detect_currency("Total: $1,200.00")
    assert result.code is None and "which dollar" in result.problems[0]


def test_conflicting_or_unknown_currency():
    assert detect_currency("Price 10 EUR, shipping 5 USD").code is None
    assert "No currency" in detect_currency("Total: 1200.00").problems[0]
    assert "not supported" in detect_currency("Currency: GBP").problems[0]


def test_currency_rounding_and_tolerance():
    assert round_money(Decimal("10.005"), "EUR") == Decimal("10.01")
    assert money_tolerance("MAD") == Decimal("0.01")


def test_language_detection():
    assert detect_languages("INVOICE\nInvoice Number: 12\nTotal due for the order") == ["en"]
    assert detect_languages("FACTURE\nNuméro de facture : 12\nMontant total TTC de la commande")[0] == "fr"
    assert detect_languages("فاتورة رقم ١٢ المجموع الإجمالي للطلبية")[0] == "ar"
    mixed = detect_languages("فاتورة رقم ١٢ المجموع الإجمالي\nFACTURE numéro 12, montant total de la commande")
    assert set(mixed) == {"ar", "fr"}


def test_locale_overrides_win():
    text = "Facture\nTotal TTC : 1 200,00 €\nDate : 03/04/2026"
    detected = detect_locale(text)
    assert (detected.language, detected.number_style, detected.currency, detected.day_first) == \
        ("fr", "comma_decimal", "EUR", True)
    forced = detect_locale(text, {"currency": "MAD", "day_first": False, "language": "auto"})
    assert forced.currency == "MAD" and forced.sources["currency"] == "user"
    assert forced.day_first is False and forced.language == "fr"
