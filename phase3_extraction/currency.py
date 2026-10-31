"""Currency identification: MAD, EUR and USD, without guessing.

"$" alone is NOT taken to mean US dollars: Canada, Australia, Mexico, Hong Kong and
others use it too. A document is only USD if it says so (USD, US$, "US dollars", or a
"Currency: USD" line). An unknown or conflicting currency stays None and is reported,
and money comparisons between documents are then blocked (see phase5 verification).
Currency conversion is deliberately out of scope.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# ISO 4217 minor units: how many decimals a price in this currency has.
MINOR_UNITS = {"MAD": 2, "EUR": 2, "USD": 2}
SUPPORTED = set(MINOR_UNITS)

_EXPLICIT = [
    ("MAD", re.compile(r"\bMAD\b|\bDHS?\b|\bDh\b|\bdirhams?\b|درهم|د\.م\.?", re.IGNORECASE)),
    ("EUR", re.compile(r"\bEUR\b|€|\beuros?\b", re.IGNORECASE)),
    ("USD", re.compile(r"\bUSD\b|\bUS\s?\$|\bU\.S\.\s?dollars?|\bUS dollars?\b|\$\s?US\b", re.IGNORECASE)),
]
_DOLLAR = re.compile(r"\$")
_DECLARED = re.compile(r"(?:currency|devise|العملة)\s*[:：]\s*([A-Z]{3})", re.IGNORECASE)


@dataclass
class CurrencyResult:
    code: str | None
    evidence: str | None = None
    problems: list[str] = field(default_factory=list)


def detect_currency(text: str) -> CurrencyResult:
    if declared := _DECLARED.search(text):
        code = declared[1].upper()
        if code in SUPPORTED:
            return CurrencyResult(code, declared[0])
        return CurrencyResult(None, declared[0], [f"Currency {code} is not supported yet (MAD, EUR, USD are)"])

    found = {code: m[0] for code, pattern in _EXPLICIT if (m := pattern.search(text))}
    if len(found) == 1:
        code, evidence = next(iter(found.items()))
        return CurrencyResult(code, evidence)
    if len(found) > 1:
        return CurrencyResult(None, None, [f"Several currencies appear ({', '.join(sorted(found))})"])
    if _DOLLAR.search(text):
        return CurrencyResult(None, "$", ["The $ sign alone does not say which dollar (US, Canadian, ...)"])
    return CurrencyResult(None, None, ["No currency is stated"])


def round_money(amount: Decimal, currency: str | None) -> Decimal:
    places = MINOR_UNITS.get(currency or "", 2)
    return amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def money_tolerance(currency: str | None) -> Decimal:
    """Half of the smallest coin rounds to the same displayed amount; allow one full unit for rounding."""
    return Decimal(1).scaleb(-MINOR_UNITS.get(currency or "", 2))
