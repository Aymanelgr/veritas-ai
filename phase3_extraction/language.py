"""Document language and locale detection (English, French, Arabic), with user overrides.

The locale bundles everything needed to read a document's values correctly:
language, number style (1,234.56 vs 1 234,56), date order (day first or month first)
and currency. Each part records whether it was detected, set by the user, or unknown.
"""

import re

from pydantic import BaseModel, Field

from phase3_extraction.currency import detect_currency
from phase3_extraction.dates import detect_day_first
from phase3_extraction.numbers import NumberStyle, detect_style

_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-zÀ-ÿ]")
_FRENCH = {"le", "la", "les", "des", "du", "de", "et", "pour", "avec", "facture", "montant", "commande",
           "fournisseur", "quantité", "prix", "unitaire", "date", "échéance", "total", "tva", "ht", "ttc",
           "désignation", "qté", "à", "au", "aux", "sur", "par", "bon", "règlement", "livraison"}
_ENGLISH = {"the", "and", "of", "to", "for", "with", "invoice", "amount", "order", "supplier", "quantity",
            "price", "unit", "due", "total", "tax", "item", "description", "bill", "purchase", "payment",
            "delivery", "please", "from", "number"}


class DocumentLocale(BaseModel):
    language: str | None = None  # en | fr | ar
    languages: list[str] = Field(default_factory=list)  # every language found (mixed documents)
    number_style: NumberStyle | None = None
    day_first: bool | None = None
    currency: str | None = None
    sources: dict[str, str] = Field(default_factory=dict)  # field -> "detected" | "user" | "unknown"
    problems: list[str] = Field(default_factory=list)  # what could not be determined, in plain words

    @property
    def rtl(self) -> bool:
        return self.language == "ar"


def detect_languages(text: str) -> list[str]:
    """Languages present, most prominent first."""
    arabic, latin = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    fr, en = sum(w in _FRENCH for w in words), sum(w in _ENGLISH for w in words)
    scores = {"ar": arabic / 4, "fr": fr * (1 if latin else 0), "en": en * (1 if latin else 0)}
    present = [lang for lang, score in sorted(scores.items(), key=lambda kv: -kv[1]) if score >= 3]
    return present or (["en"] if latin else [])


def detect_locale(text: str, overrides: dict | None = None) -> DocumentLocale:
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "", "auto")}
    locale, sources = DocumentLocale(), {}

    languages = detect_languages(text)
    locale.languages = languages
    if "language" in overrides:
        locale.language, sources["language"] = overrides["language"], "user"
    elif languages:
        locale.language, sources["language"] = languages[0], "detected"

    if "number_style" in overrides:
        locale.number_style, sources["number_style"] = overrides["number_style"], "user"
    elif style := detect_style(text):
        locale.number_style, sources["number_style"] = style, "detected"

    if "day_first" in overrides:
        locale.day_first, sources["day_first"] = bool(overrides["day_first"]), "user"
    elif (order := detect_day_first(text)) is not None:
        locale.day_first, sources["day_first"] = order, "detected"
    elif locale.language in ("fr", "ar"):
        # French- and Arabic-language documents write the day first.
        locale.day_first, sources["day_first"] = True, "detected"

    if "currency" in overrides:
        locale.currency, sources["currency"] = overrides["currency"], "user"
    else:
        found = detect_currency(text)
        locale.currency = found.code
        sources["currency"] = "detected" if found.code else "unknown"
        locale.problems += found.problems

    for key in ("number_style", "day_first"):
        sources.setdefault(key, "unknown")
    locale.sources = sources
    return locale
