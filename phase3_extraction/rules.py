"""Rule-based extraction: labels, tables and totals, in English, French and Arabic. No LLM.

Predictable and complete on tables (every row is read, however long the document), but
it only understands labels and layouts it knows. The LLM handles the rest; each fills
the other's gaps (see extractor.py).

Tables
  A row is split into cells at runs of 2+ spaces. Reading from the right: total, unit
  price, an optional unit (pcs, kg, ...), quantity; everything before is the description,
  which may start with a product code. A header line ("Item  Qty  Unit Price  Total")
  opens the table; the table stays open across page breaks, so a header repeated on
  every page is not counted as a row. Page subtotals and "carried forward" lines are
  ignored, and table-like lines that cannot be read are reported as skipped.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cache

from phase3_extraction.dates import DATE_PATTERN, dates_in
from phase3_extraction.language import DocumentLocale
from phase3_extraction.numbers import NUMBER_TOKEN, NumberStyle, normalize_digits, parse_number
from phase3_extraction.parsing import ID_PATTERN
from phase3_extraction.schemas import Adjustment, Coverage, ExtractedDocument, LineItem, TaxLine


def _labels(*words: str, colon: bool = False) -> re.Pattern:
    """A line that starts with one of the labels, then ':' (required when colon=True) and the value."""
    separator = "[:：]" if colon else "[:：]?"
    return re.compile(r"^\s*(?:" + "|".join(words) + r")\b[^:：\n]{0,40}?" + separator + r"\s*(?P<value>.*)$",
                      re.IGNORECASE)


# Header fields need "Label: value", so a sentence starting with "From ..." is not a supplier.
# Totals may omit the colon ("Total TTC   1 200,00").
LABELS = {
    "number": _labels(r"invoice\s+(?:number|no\.?|#)", r"po\s+(?:number|no\.?|#)", r"order\s+(?:number|no\.?)",
                      r"purchase\s+order\s+(?:number|no\.?)", r"n[°o]\s*(?:de\s+)?(?:facture|commande)",
                      r"num[ée]ro\s+de\s+(?:facture|commande)", r"facture\s+n[°o]", r"bon\s+de\s+commande\s+n[°o]",
                      r"رقم\s+الفاتورة", r"رقم\s+(?:أمر|طلب)\s+الشراء", r"رقم\s+الطلب", colon=True),
    "reference": _labels(r"po\s+reference", r"order\s+reference", r"your\s+order", r"r[ée]f(?:[ée]rence)?\.?\s+(?:de\s+)?commande",
                         r"votre\s+commande", r"مرجع\s+الطلب", r"رقم\s+أمر\s+الشراء\s+المرجعي", colon=True),
    "buyer": _labels(r"buyer", r"bill\s+to", r"billed\s+to", r"customer", r"client", r"acheteur", r"factur[ée]\s+[àa]",
                     r"العميل", r"المشتري", colon=True),
    "supplier": _labels(r"supplier", r"from", r"vendor", r"seller", r"fournisseur", r"vendeur", r"[ée]metteur",
                        r"المورد", r"البائع", colon=True),
    "payment_terms": _labels(r"payment\s+terms", r"terms\s+of\s+payment", r"conditions\s+de\s+(?:paiement|r[èe]glement)",
                             r"شروط\s+الدفع", colon=True),
    "subtotal": _labels(r"sub-?\s?total", r"sous-?\s?total", r"total\s+ht", r"montant\s+ht", r"total\s+hors\s+taxes?",
                        r"المجموع\s+الفرعي", r"المجموع\s+قبل\s+الضريبة"),
    "tax": _labels(r"tax", r"vat", r"tva", r"taxe", r"الضريبة", r"ضريبة\s+القيمة\s+المضافة"),
    "discount": _labels(r"discount", r"remise", r"rabais", r"r[ée]duction", r"خصم", r"تخفيض"),
    "shipping": _labels(r"shipping", r"freight", r"delivery\s+charges?", r"carriage", r"frais\s+de\s+port",
                        r"frais\s+de\s+livraison", r"مصاريف\s+الشحن", r"الشحن"),
    "credit": _labels(r"credit(?:\s+note)?", r"avoir", r"إشعار\s+دائن", r"رصيد\s+دائن"),
    "total": _labels(r"total\s+due", r"grand\s+total", r"amount\s+due", r"total\s+ttc", r"net\s+[àa]\s+payer",
                     r"montant\s+total", r"total\s+[àa]\s+payer", r"total", r"المجموع\s+الإجمالي", r"المبلغ\s+الإجمالي",
                     r"الإجمالي", r"المجموع"),
}
# Checked in this order: "Sous-total" and "Total HT" before "Total", tax before total.
TOTAL_FIELDS = ["subtotal", "discount", "shipping", "credit", "tax", "total"]

DATE_ROLES = [
    ("due_date", re.compile(r"\bdue\b|[ée]ch[ée]ance|payable|استحقاق", re.IGNORECASE)),
    ("delivery_date", re.compile(r"deliver|ship|livraison|livr[ée]|exp[ée]di|تسليم|التسليم|شحن", re.IGNORECASE)),
    ("issue_date", re.compile(r"\bdate\b|\bdated\b|التاريخ|تاريخ", re.IGNORECASE)),
]
DOC_TYPES = [
    ("invoice", re.compile(r"\binvoice\b|\bfacture\b|فاتورة", re.IGNORECASE)),
    ("purchase_order", re.compile(r"purchase\s+order|bon\s+de\s+commande|\bcommande\b|أمر\s+شراء|طلب\s+شراء", re.IGNORECASE)),
    ("contract", re.compile(r"\bcontract\b|\bagreement\b|\bcontrat\b|\bعقد\b", re.IGNORECASE)),
]
HEADER_WORDS = {
    "item", "items", "description", "designation", "désignation", "article", "product", "produit", "line", "ligne",
    "qty", "qté", "qte", "quantity", "quantité", "quantite", "unit", "unité", "price", "prix", "pu", "total",
    "amount", "montant", "الكمية", "السعر", "المجموع", "البيان", "الوصف", "المنتج", "المبلغ",
}
UNIT_WORDS = {
    "pcs", "pc", "pce", "pces", "piece", "pieces", "unit", "units", "u", "ea", "each", "kg", "g", "t", "l", "ml", "m",
    "m2", "m²", "m3", "h", "hr", "hrs", "hour", "hours", "box", "boxes", "set", "sets", "roll", "rolls", "pack",
    "lot", "pièce", "pièces", "unité", "unités", "boîte", "boite", "carton", "heure", "heures", "jour", "jours",
    "day", "days", "قطعة", "كغ", "علبة", "ساعة", "وحدة",
}
IGNORED_ROW = re.compile(r"carried\s+forward|brought\s+forward|page\s+(?:sub)?total|[àa]\s+reporter|report\s+[àa]"
                         r"|sous-total\s+page|منقول", re.IGNORECASE)
CODE = re.compile(r"^(?P<code>[A-Z]{1,4}-?\d{2,}[A-Z0-9\-/]*|\d{3,}(?:-\d+)+|#\d{2,})\s+(?P<rest>.+)$")
_MONEY_CELL = re.compile(r"^\s*(?:MAD|DHS?|EUR|USD|US\$|\$|€|درهم)?\s*[-−(]?[\d٠-٩][\d٠-٩   .,'٫٬]*\)?-?\s*"
                         r"(?:MAD|DHS?|EUR|USD|€|\$|درهم)?\s*$", re.IGNORECASE)
_QTY_WITH_UNIT = re.compile(r"^\s*(?P<qty>[-−]?[\d٠-٩][\d٠-٩.,]*)\s*(?P<unit>[^\W\d_]{1,8}\.?)\s*$")


@dataclass
class RuleResult:
    data: ExtractedDocument
    coverage: Coverage = field(default_factory=Coverage)


def _number(cell: str, style: NumberStyle | None) -> Decimal | None:
    if not _MONEY_CELL.match(normalize_digits(cell)):
        return None
    return parse_number(cell, style).value


def parse_row(line: str, style: NumberStyle | None) -> LineItem | None:
    cells = [c for c in re.split(r"\s{2,}|\t", line.strip()) if c.strip()]
    if len(cells) < 3:
        return None
    numbers, unit, i = [], None, len(cells) - 1
    while i >= 1 and len(numbers) < 3:
        value = _number(cells[i], style)
        if value is not None:
            numbers.append(value)
        elif len(numbers) == 2 and unit is None and cells[i].lower().strip(".") in UNIT_WORDS:
            unit = cells[i]  # "Qty  Unit  Price  Total"
        elif len(numbers) == 2 and (m := _QTY_WITH_UNIT.match(cells[i])) and m["unit"].lower().strip(".") in UNIT_WORDS:
            numbers.append(parse_number(m["qty"], style).value)  # "36 pcs" in one cell
            unit = m["unit"]
            i -= 1
            break
        else:
            break
        i -= 1
    if len(numbers) < 3 or None in numbers or i < 0:
        return None
    total, price, quantity = numbers
    description = " ".join(cells[: i + 1]).strip()
    code = None
    if m := CODE.match(description):
        code, description = m["code"], m["rest"].strip()
    if not re.search(r"[^\W\d_]", description):
        return None  # no words at all: not a product line
    return LineItem(description=description, quantity=quantity, unit_price=price, total=total, code=code, unit=unit)


def _is_header(line: str) -> bool:
    words = set(re.findall(r"[^\W\d_]+\.?", line.lower()))
    return len({w.strip(".") for w in words} & HEADER_WORDS) >= 2 and not NUMBER_TOKEN.search(normalize_digits(line))


def _last_amount(value: str, style: NumberStyle | None) -> Decimal | None:
    """The amount on a totals line: the last number that is not a percentage."""
    text = normalize_digits(value)
    # A number touching a "%" on either side is a rate ("20%", or "%)20" in reordered Arabic text).
    amounts = [m.group() for m in NUMBER_TOKEN.finditer(text)
               if "%" not in text[max(m.start() - 3, 0):m.start()] + text[m.end():m.end() + 3]]
    for raw in reversed(amounts):
        if (parsed := parse_number(raw, style).value) is not None:
            return parsed
    return None


@cache
def _nlp():
    import spacy

    return spacy.load("en_core_web_sm")


def _party(value: str, language: str | None) -> str | None:
    value = value.split(",")[0].split(" - ")[0].strip(" .:")
    if not value:
        return None
    if language == "en":
        # spaCy's named-entity recognizer finds organisation names (label ORG).
        orgs = [ent.text for ent in _nlp()(value).ents if ent.label_ == "ORG"]
        if orgs and len(orgs[0]) >= len(value) * 0.6:
            return orgs[0]
    return value


def rule_based_extract(text: str, locale: DocumentLocale | None = None) -> ExtractedDocument:
    return extract_with_coverage(text, locale).data


def extract_with_coverage(text: str, locale: DocumentLocale | None = None) -> RuleResult:
    locale = locale or DocumentLocale()
    style, day_first = locale.number_style, locale.day_first
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    first_lines = " ".join(lines[:6])
    doc_type = next((kind for kind, pattern in DOC_TYPES if pattern.search(first_lines)), "other")

    fields: dict = {"doc_type": doc_type, "line_items": [], "adjustments": [], "taxes": [], "currency": locale.currency}
    coverage = Coverage(pages=text.count("\f") + 1)
    ids: list[str] = []
    has_header = any(_is_header(line) for line in lines)
    in_table, headers_seen = not has_header, 0

    for line in lines:
        stripped = line.strip()
        ids += [i for i in ID_PATTERN.findall(stripped) if i not in ids]

        if _is_header(stripped):
            headers_seen += 1
            if headers_seen > 1:
                coverage.ignored_lines.append(f"repeated table header: {stripped[:80]}")
            in_table = True
            continue
        if in_table and IGNORED_ROW.search(stripped):
            coverage.ignored_lines.append(stripped[:100])
            continue
        if in_table and (row := parse_row(stripped, style)):
            fields["line_items"].append(row)
            coverage.table_rows_found += 1
            continue

        total_field = next((f for f in TOTAL_FIELDS if (m := LABELS[f].match(stripped))), None)
        if total_field and (amount := _last_amount(LABELS[total_field].match(stripped)["value"] or stripped, style)) is not None:
            label = stripped.split(":")[0].strip()[:60]
            if total_field == "tax":
                rate = re.search(r"(\d+(?:[.,]\d+)?)\s?%|%\W{0,3}(\d+(?:[.,]\d+)?)", normalize_digits(stripped))
                fields["taxes"].append(TaxLine(label=label, amount=amount,
                                               rate=parse_number(rate[1] or rate[2], style).value if rate else None))
            elif total_field in ("discount", "credit"):
                fields["adjustments"].append(Adjustment(kind=total_field, label=label, amount=-abs(amount)))
            elif total_field == "shipping":
                fields["adjustments"].append(Adjustment(kind="shipping", label=label, amount=amount))
            else:
                fields.setdefault(total_field, amount)
                if total_field == "subtotal" or total_field == "total":
                    in_table = False if has_header else in_table
            continue

        # Looks like a product row (words and at least two amounts with cents) but could not be read.
        if (in_table and len(re.findall(r"\d[.,]\d{2}(?!\d)", normalize_digits(stripped))) >= 2
                and re.search(r"[^\W\d_]{3,}", stripped) and not DATE_PATTERN.search(stripped)):
            coverage.skipped_lines.append(stripped[:120])

        for name in ("number", "reference", "buyer", "supplier", "payment_terms"):
            if (m := LABELS[name].match(stripped)) and m["value"].strip():
                value = m["value"].strip()
                if name == "number" and (found := ID_PATTERN.search(value) or re.match(r"[\w\-/]+", value)):
                    fields.setdefault("number", found.group())
                elif name == "reference":
                    fields.setdefault("_references", []).extend(ID_PATTERN.findall(value) or [value.split()[0]])
                elif name in ("buyer", "supplier"):
                    if (party := _party(value, locale.language)) and "@" not in party:
                        fields.setdefault(name, party)
                elif name == "payment_terms":
                    fields.setdefault("payment_terms", value)
                break

        if found_dates := dates_in(stripped, day_first):
            role = next((r for r, pattern in DATE_ROLES if pattern.search(stripped)), None)
            if role and role not in fields:
                fields[role] = found_dates[0]

    if fields["taxes"]:
        fields["tax"] = sum((t.amount for t in fields["taxes"]), Decimal(0))
    explicit_refs = fields.pop("_references", [])
    fields["references"] = list(dict.fromkeys(r for r in explicit_refs + ids if r != fields.get("number")))
    coverage.line_items_extracted = len(fields["line_items"])
    data = ExtractedDocument(**fields)
    coverage.missing_fields = [f for f in ("number", "issue_date", "supplier", "buyer", "total")
                               if getattr(data, f) in (None, "")]
    if not data.line_items and doc_type in ("invoice", "purchase_order"):
        coverage.missing_fields.append("line_items")
    return RuleResult(data, coverage)
