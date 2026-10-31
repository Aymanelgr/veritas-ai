"""Check what an uploaded file really is, and enforce limits, before anything processes it.

The file name's extension is only a claim. The first bytes ("magic numbers") must agree,
and each format is opened once with strict limits, so a renamed executable, a decompression
bomb or a 5,000-page PDF is rejected at the door.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

MAX_FILES_PER_UPLOAD = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60
MAX_IMAGE_PIXELS = 40_000_000  # about 6300 x 6300
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024

# Pillow refuses images larger than this when opening them (decompression-bomb protection).
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

SIGNATURES = {
    ".pdf": [b"%PDF-"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".tif": [b"II*\x00", b"MM\x00*"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
    ".bmp": [b"BM"],
    ".webp": [b"RIFF"],
    ".docx": [b"PK\x03\x04"],
}
CONTENT_TYPES = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".webp": "image/webp",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = set(CONTENT_TYPES)


class RejectedUpload(ValueError):
    """The file is not what it claims to be, or exceeds a limit."""


@dataclass
class CheckedFile:
    content_type: str
    pages: int


def check_file(path: Path, suffix: str) -> CheckedFile:
    suffix = suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise RejectedUpload(f"Unsupported file type: {suffix or 'none'}")
    head = path.open("rb").read(16)
    if suffix != ".txt" and not any(head.startswith(sig) for sig in SIGNATURES[suffix]):
        raise RejectedUpload(f"The content is not a real {suffix} file")

    if suffix == ".pdf":
        try:
            with pymupdf.open(path) as pdf:
                if pdf.needs_pass:
                    raise RejectedUpload("Password-protected PDFs are not supported")
                if pdf.page_count > MAX_PDF_PAGES:
                    raise RejectedUpload(f"The PDF has {pdf.page_count} pages; the limit is {MAX_PDF_PAGES}")
                return CheckedFile(CONTENT_TYPES[suffix], pdf.page_count)
        except RejectedUpload:
            raise
        except Exception as error:
            raise RejectedUpload(f"The PDF could not be opened: {error}") from None

    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                total = sum(info.file_size for info in archive.infolist())
        except zipfile.BadZipFile:
            raise RejectedUpload("The Word file is damaged") from None
        if "word/document.xml" not in names:
            raise RejectedUpload("The file is a ZIP archive, not a Word document")
        if total > MAX_DOCX_UNCOMPRESSED:
            raise RejectedUpload("The Word file expands to more than 50 MB")
        return CheckedFile(CONTENT_TYPES[suffix], 1)

    if suffix == ".txt":
        data = path.read_bytes()
        if b"\x00" in data:
            raise RejectedUpload("The text file contains binary data")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise RejectedUpload("Text files must be UTF-8 encoded") from None
        return CheckedFile(CONTENT_TYPES[suffix], 1)

    # Images: open and fully decode once, so truncated or oversized images fail here.
    try:
        with Image.open(path) as img:
            if img.width * img.height > MAX_IMAGE_PIXELS:
                raise RejectedUpload("The image is too large")
            img.load()
    except RejectedUpload:
        raise
    except Exception as error:
        raise RejectedUpload(f"The image could not be read: {error}") from None
    return CheckedFile(CONTENT_TYPES[suffix], 1)
