"""Generate Phase 2 test documents from the Phase 1 text samples.

Creates, in data/samples/:
  purchase_order.pdf    digital PDF (real text inside, readable by PyMuPDF)
  purchase_order.docx   Word document with a real table
  invoice_scan.png      simulated scan: rendered image, slightly rotated, with noise
  invoice_scanned.pdf   PDF that contains only that image (no text layer -> needs OCR)

Usage:
    python phase2_documents/make_samples.py
"""

from pathlib import Path

import numpy as np
import pymupdf
from docx import Document
from PIL import Image

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def text_to_pdf(text: str, out: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()  # A4-like default size
    # Courier is monospaced, so the table columns stay aligned.
    page.insert_text((50, 60), text, fontname="cour", fontsize=10)
    doc.save(out)


def text_to_docx(text: str, out: Path) -> None:
    doc = Document()
    lines = text.splitlines()
    # Lines between the "Item" header and the blank line after it form the table.
    start = next(i for i, line in enumerate(lines) if line.startswith("Item"))
    end = lines.index("", start)

    for line in lines[:start]:
        doc.add_paragraph(line)

    table = doc.add_table(rows=0, cols=4)
    for line in lines[start:end]:
        # Columns are separated by 2+ spaces in the text version.
        cells = [c for c in line.split("  ") if c.strip()]
        row = table.add_row().cells
        for cell, value in zip(row, cells):
            cell.text = value.strip()

    for line in lines[end:]:
        doc.add_paragraph(line)
    doc.save(out)


def text_to_scan(text: str, out_png: Path, out_pdf: Path) -> None:
    # Render the text as a page image at 150 DPI, like a cheap office scanner.
    tmp = pymupdf.open()
    page = tmp.new_page()
    page.insert_text((50, 60), text, fontname="cour", fontsize=10)
    pix = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)

    # Scans are never perfect: tilt the page and add grain.
    img = img.rotate(1.2, resample=Image.BICUBIC, expand=True, fillcolor=255)
    rng = np.random.default_rng(seed=42)  # fixed seed -> same image every run
    pixels = np.asarray(img, dtype=np.int16) + rng.normal(0, 18, (img.height, img.width))
    img = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
    img.save(out_png)

    # Wrap the image in a PDF: it looks like a PDF but contains no text layer.
    doc = pymupdf.open()
    page = doc.new_page(width=img.width * 72 / 150, height=img.height * 72 / 150)
    page.insert_image(page.rect, filename=str(out_png))
    doc.save(out_pdf)


def main() -> None:
    po = (SAMPLES / "purchase_order.txt").read_text(encoding="utf-8")
    invoice = (SAMPLES / "invoice.txt").read_text(encoding="utf-8")

    text_to_pdf(po, SAMPLES / "purchase_order.pdf")
    text_to_docx(po, SAMPLES / "purchase_order.docx")
    text_to_scan(invoice, SAMPLES / "invoice_scan.png", SAMPLES / "invoice_scanned.pdf")
    for path in sorted(SAMPLES.iterdir()):
        print(f"{path.name:<22} {path.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
