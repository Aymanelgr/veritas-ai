import math
from pathlib import Path

import numpy as np
import pytest

from phase1_nlp.text_analysis import analyze
from phase2_documents.reader import _group_into_lines, read_document

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def test_txt():
    doc = read_document(SAMPLES / "invoice.txt")
    assert doc.pages[0].method == "text"
    assert "INV-2026-0932" in doc.text


def test_docx_keeps_table_rows_in_order():
    doc = read_document(SAMPLES / "purchase_order.docx")
    lines = doc.text.splitlines()
    assert doc.pages[0].method == "docx"
    assert "Hydraulic pump HP-200  2  $1,250.00  $2,500.00" in lines
    assert lines.index("Item  Qty  Unit Price  Total") < lines.index("Total: $3,600.00")


def test_digital_pdf_uses_text_layer_not_ocr():
    doc = read_document(SAMPLES / "purchase_order.pdf")
    assert doc.pages[0].method == "pdf-text"
    assert "PO-2026-0147" in doc.text


def test_unsupported_type():
    with pytest.raises(ValueError):
        read_document("contract.xlsx")


def test_group_into_lines_undoes_tilt():
    # Two rows of three words on a page tilted by 2 degrees: later words sit higher.
    tilt = math.radians(-2)
    texts, polys = [], []
    for row, y in enumerate([100, 130]):
        for col, x in enumerate([50, 400, 750]):
            # Shift y along the tilt, like a real rotated scan.
            yy = y + x * math.tan(tilt)
            corners = [(x, yy), (x + 100, yy + 100 * math.tan(tilt)),
                       (x + 100, yy + 20 + 100 * math.tan(tilt)), (x, yy + 20)]
            texts.append(f"r{row}c{col}")
            polys.append(np.array(corners))
    # Shuffle so the function cannot rely on input order.
    order = [5, 0, 3, 1, 4, 2]
    result = _group_into_lines([texts[i] for i in order], [polys[i] for i in order])
    assert result == "r0c0  r0c1  r0c2\nr1c0  r1c1  r1c2"


@pytest.mark.parametrize("raw, fixed", [
    ("Payment is due by 1l/17/2026.", "Payment is due by 11/17/2026."),
    ("Total: $1,25O.00", "Total: $1,250.00"),
    ("Steel bolts M8  500", "Steel bolts M8  500"),  # words and codes are left alone
    ("Hydraulic pump HP-200", "Hydraulic pump HP-200"),
    ("Invoice lol 2026", "Invoice lol 2026"),
])
def test_digit_lookalikes_are_fixed_only_inside_numbers(raw, fixed):
    from phase2_documents.reader import fix_digit_lookalikes

    assert fix_digit_lookalikes(raw) == fixed


def test_stacked_digits_are_split_back_into_their_rows(tmp_path):
    """Two "5"s stacked in the Qty column were detected as one box and read "s 5"."""
    from scripts.make_examples import SCENARIOS, save

    scenario = next(s for s in SCENARIOS if s["folder"] == "06_arithmetic_error")
    path = tmp_path / "invoice_scan.png"
    save(scenario["files"]["invoice_scan.png"](scenario["items"]), path, seed=76)  # same image as examples/
    lines = read_document(path).text.splitlines()
    assert "Business laptop  5  $890.00  $4,450.00" in lines
    assert "USB-C docking station  5  $145.00  $725.00" in lines


@pytest.mark.parametrize("name", ["invoice_scan.png", "invoice_scanned.pdf"])
def test_ocr_finds_same_facts_as_original(name):
    """End to end: OCR + Phase 1 analysis must match the clean text exactly."""
    doc = read_document(SAMPLES / name)
    page = doc.pages[0]
    assert page.method == "ocr"
    assert page.confidence > 0.9

    expected = analyze((SAMPLES / "invoice.txt").read_text(encoding="utf-8"))["facts"]
    assert analyze(doc.text)["facts"] == expected
