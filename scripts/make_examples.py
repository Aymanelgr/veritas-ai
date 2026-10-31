"""Generate example documents for trying Veritas AI by hand.

Creates examples/<scenario>/ folders, each holding a purchase order and/or an invoice
in a mix of formats (digital PDF, Word, text, scanned PNG, scanned PDF), plus
examples/README.md (what to upload and what Veritas should find) and
examples/expected.json (the same, for scripts/check_examples.py).

Every scenario uses different companies and document numbers, so uploading all of
them at once is safe: they can't be matched with each other by mistake.

Usage:
    python scripts/make_examples.py
"""

import json
import random
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from phase2_documents.make_samples import text_to_docx, text_to_pdf  # noqa: E402

OUT = ROOT / "examples"
TAX = Decimal("0.20")


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def table(items: list[tuple[str, int, Decimal]]) -> tuple[list[str], Decimal]:
    lines = [f"{'Item':<32}{'Qty':>5}   {'Unit Price':<12} Total"]
    subtotal = Decimal(0)
    for description, qty, price in items:
        total = qty * price
        subtotal += total
        lines.append(f"{description:<32}{qty:>5}   {money(price):<12} {money(total)}")
    return lines, subtotal


def purchase_order(number, date, buyer, supplier, items, delivery, currency="USD") -> str:
    rows, subtotal = table(items)
    tax = (subtotal * TAX).quantize(Decimal("0.01"))
    return "\n".join([
        "PURCHASE ORDER", "",
        f"PO Number: {number}",
        f"Date: {date}",
        *([f"Currency: {currency}"] if currency else []),
        f"Buyer: {buyer}",
        f"Supplier: {supplier}", "",
        f"Please supply the following items. Delivery is required by {delivery}.", "",
        *rows, "",
        f"Subtotal: {money(subtotal)}",
        f"Tax (20%): {money(tax)}",
        f"Total: {money(subtotal + tax)}", "",
        "Payment terms: Net 30 days from invoice date.",
        "Any change in quantity or price must be approved in writing by the buyer.", "",
    ])


def invoice(number, date, buyer, supplier, items, shipped, due, po=None, notes=(), total_error=0,
            currency="USD") -> str:
    rows, subtotal = table(items)
    tax = (subtotal * TAX).quantize(Decimal("0.01"))
    return "\n".join([
        "INVOICE", "",
        f"Invoice Number: {number}",
        f"Invoice Date: {date}",
        *([f"Currency: {currency}"] if currency else []),
        *([f"PO Reference: {po}"] if po else []),
        f"From: {supplier}",
        f"Bill To: {buyer}", "",
        f"Thank you for your order. The goods listed below were shipped on {shipped}.", "",
        *rows, "",
        f"Subtotal: {money(subtotal)}",
        f"Tax (20%): {money(tax)}",
        f"Total Due: {money(subtotal + tax + total_error)}", "",
        *notes, *([""] if notes else []),
        f"Payment is due by {due}.", "",
    ])


def money_fr(value: Decimal) -> str:
    """French/Moroccan style: 1 234,56 DH (narrow spaces between thousands, comma decimals)."""
    whole, cents = f"{value:.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{' '.join(groups)},{cents} DH"


def french_document(kind, number, date, client, supplier, items, ref=None, due=None, delivery=None) -> str:
    """A French purchase order ("bon de commande") or invoice ("facture") in dirhams."""
    lines = [f"{'Désignation':<30}{'Qté':>5}   {'Prix unitaire':<15} Montant"]
    subtotal = Decimal(0)
    for description, qty, price in items:
        subtotal += qty * price
        lines.append(f"{description:<30}{qty:>5}   {money_fr(price):<15} {money_fr(qty * price)}")
    tax = (subtotal * TAX).quantize(Decimal("0.01"))
    title, label = ("FACTURE", "N° de facture") if kind == "invoice" else ("BON DE COMMANDE", "N° de commande")
    return "\n".join([
        title, "",
        f"{label} : {number}",
        f"Date : {date}",
        *([f"Réf. commande : {ref}"] if ref else []),
        "Devise : MAD",
        f"Fournisseur : {supplier}",
        f"Client : {client}", "",
        *([f"Livraison exigée avant le {delivery}."] if delivery else []), "",
        *lines, "",
        f"Total HT : {money_fr(subtotal)}",
        f"TVA (20 %) : {money_fr(tax)}",
        f"Total TTC : {money_fr(subtotal + tax)}", "",
        *([f"Échéance : {due}"] if due else []),
        "Conditions de paiement : 30 jours fin de mois.", "",
    ])


ARABIC_FONT = Path("C:/Windows/Fonts/arial.ttf")


def arabic_document(kind, number, date, client, supplier, items, ref=None) -> str:
    """An Arabic purchase order or invoice in dirhams (Western digits, as is common in Morocco)."""
    gap = " " * 4  # non-breaking spaces keep the column gaps (HTML would collapse normal spaces)
    rows = []
    subtotal = Decimal(0)
    for description, qty, price in items:
        subtotal += qty * price
        rows.append(gap.join([description, str(qty), f"{price:.2f}", f"{qty * price:.2f}"]))
    tax = (subtotal * TAX).quantize(Decimal("0.01"))
    title, label = ("فاتورة", "رقم الفاتورة") if kind == "invoice" else ("أمر شراء", "رقم الطلب")
    return "\n".join([
        title,
        f"{label}: {number}",
        f"التاريخ: {date}",
        *([f"مرجع الطلب: {ref}"] if ref else []),
        "العملة: MAD",
        f"المورد: {supplier}",
        f"العميل: {client}",
        "",
        gap.join(["البيان", "الكمية", "السعر", "المجموع"]),
        *rows,
        "",
        f"المجموع الفرعي: {subtotal:.2f} درهم",
        f"الضريبة (20%): {tax:.2f} درهم",
        f"المجموع الإجمالي: {subtotal + tax:.2f} درهم",
    ])


def arabic_pdf(text: str, path: Path) -> None:
    """Right-to-left Arabic needs a font with Arabic letters and text shaping (HTML box)."""
    doc = pymupdf.open()
    page = doc.new_page()
    html = "".join(f"<p>{line or '&nbsp;'}</p>" for line in text.splitlines())
    css = "* {font-family: ar; font-size: 11pt; direction: rtl; text-align: right; margin: 0 0 4pt 0;}" \
          f" @font-face {{font-family: ar; src: url({ARABIC_FONT.name});}}"
    page.insert_htmlbox(page.rect + (50, 50, -50, -50), html, css=css,
                        archive=pymupdf.Archive(str(ARABIC_FONT.parent)))
    doc.save(path)


def scan_image(text: str, seed: int) -> Image.Image:
    """Render text like a cheap office scan: 150 DPI, slightly tilted, grainy."""
    rng = random.Random(seed)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), text, fontname="cour", fontsize=10)
    pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    img = img.rotate(rng.uniform(-1.5, 1.5), resample=Image.BICUBIC, expand=True, fillcolor=255)
    noise = np.random.default_rng(seed).normal(0, rng.uniform(10, 18), (img.height, img.width))
    return Image.fromarray(np.clip(np.asarray(img, dtype=np.int16) + noise, 0, 255).astype(np.uint8))


def save(text: str, path: Path, seed: int = 0) -> None:
    """Write `text` in the format given by the file extension."""
    kind = path.name.rsplit(".", 2)
    if "arabic" in path.stem:
        arabic_pdf(text, path)
    elif path.suffix == ".txt":
        path.write_text(text, encoding="utf-8")
    elif path.suffix == ".docx":
        text_to_docx(text, path)
    elif path.suffix == ".png":
        scan_image(text, seed).save(path)
    elif path.suffix == ".pdf" and "scanned" in path.stem:
        img = scan_image(text, seed)
        png = path.with_suffix(".tmp.png")
        img.save(png)
        doc = pymupdf.open()
        page = doc.new_page(width=img.width * 72 / 150, height=img.height * 72 / 150)
        page.insert_image(page.rect, filename=str(png))
        doc.save(path)
        png.unlink()
    elif path.suffix == ".pdf":
        text_to_pdf(text, path)
    else:
        raise ValueError(kind)


D = Decimal
SCENARIOS = [
    {
        "folder": "01_perfect_match",
        "title": "Perfect match",
        "story": "The invoice matches the order exactly.",
        "expect": "Linked by the PO reference. All checks pass; nothing to review.",
        "linked_po": "PO-2026-1101", "problems": [],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1101", "2026-09-01", "Horizon Dental Clinic", "Brightway Office Supplies", items,
                "September 20, 2026"),
            "invoice_scan.png": lambda items: invoice(
                "INV-2026-5101", "2026-09-12", "Horizon Dental Clinic", "Brightway Office Supplies", items,
                "September 11, 2026", "10/12/2026", po="PO-2026-1101"),
        },
        "items": [("Ergonomic office chair", 4, D("189.00")), ("Standing desk", 2, D("420.00")),
                  ("Monitor arm", 4, D("65.00"))],
    },
    {
        "folder": "02_quantity_mismatch",
        "title": "Quantity changed without approval",
        "story": "3 microscopes were ordered; the invoice bills 4. Nothing explains the change.",
        "expect": "CRITICAL: invoiced quantity of 'Microscope LX-400' does not match (3 vs 4), no approval found.",
        "linked_po": "PO-2026-1102", "problems": [["quantity_match", "critical"]],
        "files": {
            "purchase_order.docx": lambda items: purchase_order(
                "PO-2026-1102", "2026-08-18", "Greenfield University", "Delta Lab Equipment", items,
                "September 10, 2026"),
            "invoice_scanned.pdf": lambda items: invoice(
                "INV-2026-5102", "2026-09-05", "Greenfield University", "Delta Lab Equipment",
                [("Microscope LX-400", 4, D("980.00")), *items[1:]],
                "September 4, 2026", "10/05/2026", po="PO-2026-1102"),
        },
        "items": [("Microscope LX-400", 3, D("980.00")), ("Lab coat (white)", 25, D("18.50")),
                  ("Pipette set", 10, D("45.00"))],
    },
    {
        "folder": "03_approved_change",
        "title": "Quantity changed, with documented approval",
        "story": "40 life jackets ordered, 50 invoiced, and the invoice notes the buyer approved it by email.",
        "expect": "WARNING (not critical): the quantity difference is flagged but explained by the approval line.",
        "linked_po": "PO-2026-1103", "problems": [["quantity_match", "warning"]],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1103", "2026-08-25", "Bluewater Ferries", "Coastline Marine Parts", items,
                "September 15, 2026"),
            "invoice.txt": lambda items: invoice(
                "INV-2026-5103", "2026-09-10", "Bluewater Ferries", "Coastline Marine Parts",
                [items[0], ("Life jacket (adult)", 50, D("32.00")), items[2]],
                "September 9, 2026", "10/10/2026", po="PO-2026-1103",
                notes=["Quantity of life jackets increased to 50 as approved by the buyer by email on 2026-09-02."]),
        },
        "items": [("Bilge pump BP-12", 2, D("340.00")), ("Life jacket (adult)", 40, D("32.00")),
                  ("Navigation light", 6, D("75.00"))],
    },
    {
        "folder": "04_price_increase",
        "title": "Unit price increased",
        "story": "LED panels ordered at $28.00 each are invoiced at $31.50.",
        "expect": "CRITICAL: invoiced unit price of 'LED panel 60x60' does not match the order.",
        "linked_po": "PO-2026-1104", "problems": [["unit_price_match", "critical"]],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1104", "2026-07-30", "Northpoint Hotel Group", "Summit Electrical Wholesale", items,
                "August 25, 2026"),
            "invoice_scan.png": lambda items: invoice(
                "INV-2026-5104", "2026-08-20", "Northpoint Hotel Group", "Summit Electrical Wholesale",
                [("LED panel 60x60", 30, D("31.50")), *items[1:]],
                "August 19, 2026", "09/19/2026", po="PO-2026-1104"),
        },
        "items": [("LED panel 60x60", 30, D("28.00")), ("Circuit breaker 32A", 20, D("22.00")),
                  ("Cable tray 3m", 15, D("19.00"))],
    },
    {
        "folder": "05_unexpected_item",
        "title": "Item that was never ordered",
        "story": "The invoice adds a hedge trimmer that is not on the purchase order.",
        "expect": "CRITICAL: 'Hedge trimmer HT-20' was not ordered.",
        "linked_po": "PO-2026-1105", "problems": [["unexpected_item", "critical"]],
        "files": {
            "purchase_order.docx": lambda items: purchase_order(
                "PO-2026-1105", "2026-09-03", "Sunrise Property Management", "Evergreen Garden Supply", items,
                "September 24, 2026"),
            "invoice.pdf": lambda items: invoice(
                "INV-2026-5105", "2026-09-18", "Sunrise Property Management", "Evergreen Garden Supply",
                [*items, ("Hedge trimmer HT-20", 1, D("180.00"))],
                "September 17, 2026", "10/18/2026", po="PO-2026-1105"),
        },
        "items": [("Lawn mower GM-50", 1, D("650.00")), ("Garden hose 30m", 6, D("35.00")),
                  ("Fertilizer 25kg bag", 10, D("28.00"))],
    },
    {
        "folder": "06_arithmetic_error",
        "title": "Total that does not add up",
        "story": "Every line is right, but the invoice's grand total is $100 too high.",
        "expect": "CRITICAL: subtotal plus tax does not equal the total.",
        "linked_po": "PO-2026-1106", "problems": [["total_arithmetic", "critical"]],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1106", "2026-09-07", "Crescent Law Partners", "Pioneer IT Distribution", items,
                "September 21, 2026"),
            "invoice_scan.png": lambda items: invoice(
                "INV-2026-5106", "2026-09-16", "Crescent Law Partners", "Pioneer IT Distribution", items,
                "September 15, 2026", "10/16/2026", po="PO-2026-1106", total_error=D(100)),
        },
        "items": [("Business laptop", 5, D("890.00")), ("USB-C docking station", 5, D("145.00")),
                  ("Wireless mouse", 5, D("24.00"))],
    },
    {
        "folder": "07_no_po_reference",
        "title": "Invoice without a PO number",
        "story": "The invoice never mentions the PO number, writes the supplier name differently and rewords every item.",
        "expect": "Linked anyway by fuzzy matching (supplier, buyer, items, dates). All checks pass.",
        "linked_po": "PO-2026-1107", "problems": [],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1107", "2026-08-12", "Oakridge Bakery", "Meridian Print & Packaging", items,
                "August 30, 2026"),
            "invoice_scan.png": lambda items: invoice(
                "INV-2026-5107", "2026-08-28", "Oakridge Bakery", "MERIDIAN PRINT AND PACKAGING LTD",
                [("40x30x20 corrugated boxes", 200, D("1.20")), ("48mm packing tape", 36, D("3.50")),
                 ("A6 shipping label roll", 12, D("14.00"))],
                "August 27, 2026", "09/27/2026"),
        },
        "items": [("Corrugated box 40x30x20", 200, D("1.20")), ("Packing tape 48mm", 36, D("3.50")),
                  ("Shipping labels A6 (roll)", 12, D("14.00"))],
    },
    {
        "folder": "08_orphan_invoice",
        "title": "Invoice with no purchase order",
        "story": "A cleaning company sends an invoice, but no matching order exists.",
        "expect": "WARNING: no matching purchase order was found. The invoice's own arithmetic is correct.",
        "linked_po": None, "problems": [["matching_order", "warning"]],
        "files": {
            "invoice.docx": lambda items: invoice(
                "INV-2026-5108", "2026-09-20", "Riverside Library", "Quantum Cleaning Services", items,
                "September 19, 2026", "10/20/2026"),
        },
        "items": [("Deep cleaning (hours)", 24, D("38.00")), ("Window cleaning (floors)", 3, D("150.00"))],
    },
    {
        "folder": "09_partial_invoice",
        "title": "Partial invoice",
        "story": "Three items were ordered; this invoice bills only two (the third ships later).",
        "expect": "No problems. 'Anchor bolt kit' is listed as not billed on this invoice: information only, since it may be invoiced separately (partial invoicing).",
        "linked_po": "PO-2026-1109", "problems": [],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1109", "2026-08-05", "Westbridge Construction", "Harbor Steel Fabrication", items,
                "September 5, 2026"),
            "invoice_scanned.pdf": lambda items: invoice(
                "INV-2026-5109", "2026-08-29", "Westbridge Construction", "Harbor Steel Fabrication", items[:2],
                "August 28, 2026", "09/28/2026", po="PO-2026-1109"),
        },
        "items": [("Steel beam HEA 200 (6m)", 8, D("410.00")), ("Base plate 300x300", 16, D("55.00")),
                  ("Anchor bolt kit", 16, D("24.00"))],
    },
    {
        "folder": "10_late_delivery",
        "title": "Late delivery",
        "story": "The order required delivery by September 15; the goods shipped on September 22.",
        "expect": "WARNING: goods were not shipped by the required delivery date.",
        "linked_po": "PO-2026-1110", "problems": [["delivery_deadline", "warning"]],
        "files": {
            "purchase_order.txt": lambda items: purchase_order(
                "PO-2026-1110", "2026-09-01", "Maple Street Cafe", "Alpine Food Distributors", items,
                "September 15, 2026"),
            "invoice_scan.png": lambda items: invoice(
                "INV-2026-5110", "2026-09-23", "Maple Street Cafe", "Alpine Food Distributors", items,
                "September 22, 2026", "10/23/2026", po="PO-2026-1110"),
        },
        "items": [("Espresso beans 1kg", 20, D("24.00")), ("Oat milk 1L (case of 6)", 10, D("15.60")),
                  ("Paper cups 12oz (box)", 8, D("32.00"))],
    },
    {
        "folder": "11_currency_not_stated",
        "title": "Currency not stated",
        "story": "Both documents show prices with a '$' sign but never say which dollar.",
        "expect": "WARNING: prices and totals NOT compared because the currency is unknown "
                  "('$' alone is not assumed to be US dollars). Quantities are still checked.",
        "linked_po": "PO-2026-1111", "problems": [["currency_match", "warning"]],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1111", "2026-09-02", "Lakeside Veterinary Clinic", "Prairie Medical Supply", items,
                "September 20, 2026", currency=None),
            "invoice.pdf": lambda items: invoice(
                "INV-2026-5111", "2026-09-14", "Lakeside Veterinary Clinic", "Prairie Medical Supply", items,
                "September 13, 2026", "10/14/2026", po="PO-2026-1111", currency=None),
        },
        "items": [("Surgical gloves (box)", 30, D("12.00")), ("Syringe 5ml (pack)", 15, D("8.50"))],
    },
    {
        "folder": "12_currency_mismatch",
        "title": "Different currencies",
        "story": "The order is in euros; the invoice for the same goods is in Moroccan dirhams.",
        "expect": "CRITICAL: the invoice currency (MAD) differs from the order (EUR). Prices and totals are "
                  "NOT compared, because there is no currency conversion.",
        "linked_po": "PO-2026-1112", "problems": [["currency_match", "critical"]],
        "files": {
            "purchase_order.pdf": lambda items: purchase_order(
                "PO-2026-1112", "2026-09-04", "Marina Boat Club", "Iberia Rope Works", items,
                "September 25, 2026", currency="EUR"),
            "invoice.pdf": lambda items: invoice(
                "INV-2026-5112", "2026-09-18", "Marina Boat Club", "Iberia Rope Works", items,
                "September 17, 2026", "10/18/2026", po="PO-2026-1112", currency="MAD"),
        },
        "items": [("Mooring rope 20m", 10, D("48.00")), ("Fender large", 8, D("35.00"))],
    },
    {
        "folder": "13_french_dirhams",
        "title": "French documents in dirhams",
        "story": "A French purchase order and a SCANNED French invoice: '1 234,56 DH' numbers, day-first dates "
                 "(18/09/2026), accents. The invoice bills 50 reams of paper instead of 40.",
        "expect": "CRITICAL: quantity of 'Ramette papier A4' differs (40 ordered, 50 invoiced), with the "
                  "money impact in MAD. Amounts read correctly despite the French number format.",
        "linked_po": "BC-2026-0413", "problems": [["quantity_match", "critical"]],
        "files": {
            "bon_de_commande.pdf": lambda items: french_document(
                "order", "BC-2026-0413", "05/09/2026", "Clinique Al Amal", "Atlas Bureautique SARL", items,
                delivery="25/09/2026"),
            "facture_scan.png": lambda items: french_document(
                "invoice", "FAC-2026-0413", "18/09/2026", "Clinique Al Amal", "Atlas Bureautique SARL",
                [("Ramette papier A4", 50, D("45.00")), *items[1:]], ref="BC-2026-0413", due="18/10/2026"),
        },
        "items": [("Ramette papier A4", 40, D("45.00")), ("Cartouche d'encre noire", 12, D("320.50")),
                  ("Classeur à levier", 60, D("18.90"))],
    },
    {
        "folder": "14_arabic",
        "title": "Arabic documents",
        "story": "An Arabic purchase order and invoice (right-to-left text, MAD). They match exactly.",
        "expect": "Linked by the order reference; no problems. (Arabic support is EXPERIMENTAL: see the "
                  "README's language section for what was evaluated.)",
        "linked_po": "PO-2026-1114", "problems": [],
        "files": {
            "purchase_order_arabic.pdf": lambda items: arabic_document(
                "order", "PO-2026-1114", "2026-09-06", "مقهى الأندلس", "شركة الأطلس للتوريدات", items),
            "invoice_arabic.pdf": lambda items: arabic_document(
                "invoice", "INV-2026-5114", "2026-09-20", "مقهى الأندلس", "شركة الأطلس للتوريدات", items,
                ref="PO-2026-1114"),
        },
        "items": [("قهوة عربية 1 كغ", 10, D("120.00")), ("سكر 5 كغ", 6, D("45.50"))],
    },
]


def write_readme(scenarios: list[dict]) -> None:
    lines = [
        "# Example documents for Veritas AI", "",
        "Ten realistic scenarios to upload and test. Formats are mixed on purpose: digital PDFs,",
        "Word files, text files, and **scanned** images/PDFs (slightly tilted and grainy, like a",
        "real office scanner), so OCR is exercised too.", "",
        "## How to use", "",
        "1. Open the dashboard (http://localhost:5173) and make sure the worker is running.",
        "2. Drag **all the files of one folder** onto the upload box (or several folders at once:",
        "   the companies and numbers are all different, so they can't be mixed up).",
        "3. Wait until both documents say *processed* (OCR takes ~15 s per scanned page).",
        "4. Open the **invoice** and compare with the expected result below.", "",
        "Tip: upload the purchase order first. The invoice is linked as soon as both exist, in either order.", "",
        "## Scenarios", "",
        "| Folder | Files | Situation | Veritas should show |",
        "|---|---|---|---|",
    ]
    for s in scenarios:
        files = ", ".join(f"`{f}`" for f in s["files"])
        lines.append(f"| `{s['folder']}` | {files} | **{s['title']}.** {s['story']} | {s['expect']} |")
    lines += [
        "", "## Things to try on the way", "",
        "- **Ctrl+K** and type a company name or number to jump to a document.",
        "- On an invoice page, hover a problem: its row lights up in *Order vs invoice*.",
        "- Click a scanned page to zoom; click an extracted value to see the line it came from.",
        "- Ask: *\"How many life jackets were ordered and how many were invoiced?\"* or",
        "  *\"Which invoices are from Summit Electrical Wholesale?\"*",
        "- In *Reviews*, use **J/K** to move, **C** to confirm, **D** to dismiss, and **Undo** in the toast.", "",
        "To regenerate these files: `python scripts/make_examples.py`.",
        "To check them automatically (no upload needed): `python scripts/check_examples.py`.", "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    expected = []
    for seed, s in enumerate(SCENARIOS, start=1):
        folder = OUT / s["folder"]
        folder.mkdir(exist_ok=True)
        for name, build in s["files"].items():
            save(build(s["items"]), folder / name, seed=seed * 10 + len(name))
        invoice_file = next(name for name in s["files"] if name.startswith(("invoice", "facture")))
        expected.append({"folder": s["folder"], "invoice_file": invoice_file,
                         "linked_po": s["linked_po"], "problems": s["problems"]})
        print(f"{s['folder']:<24} {', '.join(s['files'])}")
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    write_readme(SCENARIOS)
    print(f"\nWrote {sum(len(s['files']) for s in SCENARIOS)} documents to {OUT}")


if __name__ == "__main__":
    main()
