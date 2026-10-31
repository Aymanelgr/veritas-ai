"""Phase 2 - Document-reading pipeline for Veritas AI.

One entry point, read_document(path), turns any supported file into text:

  .txt                  read directly
  .docx                 python-docx (paragraphs and tables, in document order)
  .pdf                  PyMuPDF text layer; pages with no text layer fall back to OCR
  .png .jpg .jpeg ...   PaddleOCR

Every page records HOW it was read, for OCR how confident the model was and which
language model read it, and each text line's position on the page (so a finding can
highlight the exact region of the original document).

OCR languages: the "latin" recognition model reads English and French (accents
included); the Arabic model reads Arabic. Pass language="ar" for Arabic scans. With
language=None, a page the latin model reads poorly is retried with the Arabic model
and the more confident reading is kept.

Usage (from the project root):
    python -m phase2_documents.reader data/samples/invoice_scan.png
    python -m phase2_documents.reader scan.png --language ar
"""

import argparse
import io
import math
import re
from functools import cache
from pathlib import Path
from statistics import median
from typing import Literal

import numpy as np
import pymupdf
from docx import Document
from docx.table import Table
from PIL import Image
from pydantic import BaseModel, Field

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# A PDF page with fewer characters than this is treated as scanned and sent to OCR.
MIN_TEXT_CHARS = 20
# Resolution used when rendering a scanned PDF page to an image for OCR.
OCR_DPI = 200

# The "mobile" models are ~3x faster on CPU than the default ones, with the
# same accuracy on our invoices.
DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODELS = {
    "latin": "latin_PP-OCRv5_mobile_rec",  # English, French and other Latin-script languages
    "en": "en_PP-OCRv5_mobile_rec",
    "ar": "arabic_PP-OCRv5_mobile_rec",
}
# Chosen by measurement on our English scans: the English model made 2 character errors
# in 3,656, the latin one 6 (0.05% vs 0.16%). The latin model is used for French because
# the English one cannot read accents (é, è, à, ç).
LANGUAGE_MODEL = {"en": "en", "fr": "latin", "ar": "ar"}
RECOGNITION_MODEL = RECOGNITION_MODELS["en"]
# Below this mean confidence, an unknown-language page is retried with the Arabic model.
RETRY_CONFIDENCE = 0.80
_ARABIC = re.compile(r"[؀-ۿ]")


class TextLine(BaseModel):
    text: str
    bbox: list[float] = Field(description="x0, y0, x1, y1 as fractions of the page width and height")


class Page(BaseModel):
    number: int
    text: str
    method: Literal["text", "docx", "pdf-text", "ocr"]
    confidence: float | None = None  # mean OCR score (0-1); None when not OCR
    ocr_model: str | None = None
    lines: list[TextLine] = Field(default_factory=list)  # positions, when the format has them


class DocumentText(BaseModel):
    path: str
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


def read_document(path: str | Path, language: str | None = None, on_page=None) -> DocumentText:
    """Read a document. `on_page(page_number, page_count)` is called as each page is read."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        pages = [Page(number=1, text=path.read_text(encoding="utf-8"), method="text")]
    elif suffix == ".docx":
        pages = [Page(number=1, text=_read_docx(path), method="docx")]
    elif suffix == ".pdf":
        pages = _read_pdf(path, language, on_page)
    elif suffix in IMAGE_EXTENSIONS:
        image = np.asarray(Image.open(path).convert("RGB"))
        pages = [_ocr_page(1, image, language)]
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    return DocumentText(path=str(path), pages=pages)


def _read_docx(path: Path) -> str:
    lines = []
    # iter_inner_content() yields paragraphs and tables in the order they appear.
    for block in Document(str(path)).iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                lines.append("  ".join(cell.text for cell in row.cells))
        else:
            lines.append(block.text)
    return "\n".join(lines)


def _pdf_lines(page: pymupdf.Page) -> list[TextLine]:
    width, height = page.rect.width, page.rect.height
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = " ".join(span["text"] for span in line["spans"]).strip()
            if text:
                x0, y0, x1, y1 = line["bbox"]
                lines.append(TextLine(text=text, bbox=[x0 / width, y0 / height, x1 / width, y1 / height]))
    return lines


_PRESENTATION_FORMS = re.compile(r"[ﭐ-﷿ﹰ-﻿]")


def _logical_line(line: str) -> str:
    """Turn a visually ordered Arabic line (as many PDFs store it) into reading order.

    Such PDFs store right-to-left text left-to-right, using "presentation form" glyphs.
    Cells (separated by 2+ spaces, e.g. table columns) are reversed; inside a cell, runs
    of Arabic words are reversed while runs of numbers/Latin text keep their order, so
    "20-09-2026" and "INV-2026-5114" stay intact.
    """
    import unicodedata

    line = line.replace("­", "-")  # soft hyphens stand in for "-" in some PDFs
    if not _PRESENTATION_FORMS.search(line):
        return line
    cells = re.split(r"([\s ]{2,})", unicodedata.normalize("NFKC", line))
    logical_cells = []
    for cell in cells[::2][::-1]:
        runs, current, current_ar = [], [], None
        for token in cell.split():
            is_ar = bool(_ARABIC.search(token))
            if current and is_ar != current_ar:
                runs.append((current_ar, current))
                current = []
            current.append(token)
            current_ar = is_ar
        if current:
            runs.append((current_ar, current))
        logical_cells.append(" ".join(" ".join(toks[::-1] if ar else toks) for ar, toks in runs[::-1]))
    logical = "    ".join(c for c in logical_cells if c)
    return re.sub(r"(\d) ?([-/.]) ?(?=\d)", r"\1\2", logical)  # "20 - 09 - 2026" -> "20-09-2026"


def _read_pdf(path: Path, language: str | None, on_page=None) -> list[Page]:
    pages = []
    with pymupdf.open(path) as pdf:
        for number, page in enumerate(pdf, start=1):
            if on_page:
                on_page(number, pdf.page_count)
            text = page.get_text("text", sort=True)
            if len(text.strip()) >= MIN_TEXT_CHARS:
                lines = _pdf_lines(page)
                if _PRESENTATION_FORMS.search(text) or "­" in text:
                    text = "\n".join(_logical_line(line) for line in text.splitlines())
                    for line in lines:
                        line.text = _logical_line(line.text)
                pages.append(Page(number=number, text=text, method="pdf-text", lines=lines))
                continue
            # No usable text layer: this page is a picture, so OCR it.
            pages.append(_ocr_page(number, _page_image(pdf, page), language))
    return pages


def _page_image(pdf: pymupdf.Document, page: pymupdf.Page) -> np.ndarray:
    images = page.get_images()
    if len(images) == 1:
        # A typical scan: one image fills the page. Extract it at its original
        # resolution - re-rendering would resample it, and the slight blur makes
        # OCR confuse look-alike characters (we saw "11/17" read as "1l/17").
        data = pdf.extract_image(images[0][0])["image"]
        return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))

    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csRGB)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


@cache
def _ocr_engine(model: str = "en"):
    # Imported here because loading PaddleOCR takes seconds; text-only files skip it.
    from paddleocr import PaddleOCR

    return PaddleOCR(
        text_detection_model_name=DETECTION_MODEL,
        text_recognition_model_name=RECOGNITION_MODELS[model],
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        # oneDNN crashes in PaddlePaddle 3.3 on Windows ("ConvertPirAttribute2RuntimeAttribute").
        enable_mkldnn=False,
    )


@cache
def _recognizer(model: str = "en"):
    from paddleocr import TextRecognition

    return TextRecognition(model_name=RECOGNITION_MODELS[model], enable_mkldnn=False)


def _ocr_page(number: int, rgb: np.ndarray, language: str | None) -> Page:
    """OCR one page. Without a known language: read with the English model, detect the
    language from what was read, and re-read with the French (latin) or Arabic model if needed."""
    from phase3_extraction.language import detect_languages

    model = LANGUAGE_MODEL.get(language, "en")
    text, confidence, lines = _ocr(rgb, model)
    if language is None:
        retry = None
        if "fr" in detect_languages(text)[:1]:
            retry = "latin"
        elif (confidence or 0) < RETRY_CONFIDENCE:
            retry = "ar"  # possibly not a Latin-script page
        if retry:
            new_text, new_confidence, new_lines = _ocr(rgb, retry)
            better = (new_confidence or 0) >= (confidence or 0) - 0.02 if retry == "latin" else \
                (new_confidence or 0) > (confidence or 0) and _ARABIC.search(new_text)
            if better:
                text, confidence, lines, model = new_text, new_confidence, new_lines, retry
    return Page(number=number, text=text, method="ocr", confidence=confidence,
                ocr_model=RECOGNITION_MODELS[model], lines=lines)


def ocr_image(rgb: np.ndarray, model: str = "en") -> tuple[str, float | None]:
    """OCR an RGB image and return (text, mean confidence)."""
    text, confidence, _ = _ocr(rgb, model)
    return text, confidence


_NUMERIC_TOKEN = re.compile(r"[\dlIO|o/.,:\-]{4,}")
_LOOKALIKES = str.maketrans({"l": "1", "I": "1", "|": "1", "O": "0", "o": "0"})


def fix_digit_lookalikes(text: str) -> str:
    """OCR often reads 1 as l/I/| and 0 as O/o inside numbers ("1l/17/2026").

    Only tokens that are clearly numbers or dates (at least 3 digits, at most 2 look-alike
    letters, nothing else) are corrected, so words and codes like "M8" or "HP-200" are untouched.
    """
    def fix(match: re.Match) -> str:
        token = match.group()
        digits = sum(c.isdigit() for c in token)
        lookalikes = sum(c in "lIO|o" for c in token)
        return token.translate(_LOOKALIKES) if digits >= 3 and 0 < lookalikes <= 2 else token

    return re.sub(r"(?<![^\W\d_])" + _NUMERIC_TOKEN.pattern + r"(?![^\W\d_])", fix, text)


def _ocr(rgb: np.ndarray, model: str) -> tuple[str, float | None, list[TextLine]]:
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])  # PaddleOCR expects OpenCV's BGR order
    result = _ocr_engine(model).predict(bgr)[0]
    texts = [fix_digit_lookalikes(t) for t in result["rec_texts"]]
    texts, scores, polys = _split_multiline_boxes(
        bgr, texts, result["rec_scores"], result["rec_polys"], result["rec_boxes"], model)
    if not texts:
        return "", None, []
    lines = _lines_with_boxes(texts, polys, width=rgb.shape[1], height=rgb.shape[0])
    return "\n".join(line.text for line in lines), float(np.mean(scores)), lines


def _split_multiline_boxes(bgr, texts, scores, polys, boxes, model: str = "en"):
    """Re-read boxes that cover more than one text line.

    The detector sometimes merges text stacked in a table column (a "5" directly above
    another "5") into one tall box; it is then misread ("s 5") and lands on the wrong
    line. A box about twice as tall as a normal line is cut into one slice per line,
    and each slice is recognized on its own.
    """
    if not texts:
        return texts, scores, polys
    line_height = median(math.dist(p[0], p[3]) for p in polys)
    out_texts, out_scores, out_polys = [], [], []
    for text, score, poly, box in zip(texts, scores, polys, boxes):
        lines = round(math.dist(poly[0], poly[3]) / line_height)
        if lines < 2:
            out_texts.append(text)
            out_scores.append(score)
            out_polys.append(poly)
            continue
        x1, y1, x2, y2 = (int(v) for v in box)
        step = (y2 - y1) / lines
        rects = [(int(y1 + i * step), int(y1 + (i + 1) * step)) for i in range(lines)]
        crops = [bgr[max(top - 2, 0):bottom + 2, x1:x2] for top, bottom in rects]
        for res, (top, bottom) in zip(_recognizer(model).predict(crops), rects):
            if res["rec_text"].strip():
                out_texts.append(res["rec_text"])
                out_scores.append(float(res["rec_score"]))
                out_polys.append(np.array([[x1, top], [x2, top], [x2, bottom], [x1, bottom]], dtype=float))
    return out_texts, out_scores, out_polys


def _lines_with_boxes(texts: list[str], polys: list[np.ndarray], width: float = 1.0,
                      height: float = 1.0) -> list[TextLine]:
    """Rebuild reading order from OCR boxes, keeping each line's position.

    OCR returns separate boxes (e.g. "Item", "Qty", "Unit Price"), not lines. On a
    tilted scan, boxes on the same line sit at different heights, so we first
    measure the tilt and rotate the box centres back to horizontal ("deskew").
    Arabic lines are read right to left.
    """
    # Each poly is 4 corners starting top-left, clockwise. The top edge gives the tilt.
    angles = [math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0]) for p in polys]
    skew = median(angles)
    cos, sin = math.cos(skew), math.sin(skew)

    boxes = []
    for text, poly in zip(texts, polys):
        cx, cy = poly.mean(axis=0)
        h = math.dist(poly[0], poly[3])
        # Rotate the centre by -skew so every line becomes horizontal.
        x = cx * cos + cy * sin
        y = -cx * sin + cy * cos
        boxes.append((y, x, h, text, poly))

    boxes.sort(key=lambda b: (b[0], b[1]))
    threshold = median(b[2] for b in boxes) / 2
    groups, current = [], [boxes[0]]
    for box in boxes[1:]:
        if box[0] - current[0][0] > threshold:  # far below the line's first box -> new line
            groups.append(current)
            current = []
        current.append(box)
    groups.append(current)

    lines = []
    for group in groups:
        arabic = sum(len(_ARABIC.findall(b[3])) for b in group) > sum(len(b[3]) for b in group) / 2
        ordered = sorted(group, key=lambda b: b[1], reverse=arabic)  # right-to-left for Arabic
        points = np.vstack([b[4] for b in ordered])
        x0, y0 = points.min(axis=0)
        x1, y1 = points.max(axis=0)
        lines.append(TextLine(text="  ".join(b[3] for b in ordered),
                              bbox=[float(x0 / width), float(y0 / height), float(x1 / width), float(y1 / height)]))
    return lines


def _group_into_lines(texts: list[str], polys: list[np.ndarray]) -> str:
    return "\n".join(line.text for line in _lines_with_boxes(texts, polys))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read documents into text.")
    parser.add_argument("files", nargs="+", type=Path, help="documents to read")
    parser.add_argument("--language", choices=["en", "fr", "ar"], help="force the OCR language")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args()

    for path in args.files:
        doc = read_document(path, args.language)
        if args.json:
            print(doc.model_dump_json(indent=2))
            continue
        print(f"\n=== {path.name} ===")
        for page in doc.pages:
            score = f", confidence {page.confidence:.3f} ({page.ocr_model})" if page.confidence is not None else ""
            print(f"[page {page.number}: {page.method}{score}]")
            print(page.text.strip())


if __name__ == "__main__":
    main()
