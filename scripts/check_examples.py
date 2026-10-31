"""Run every example through the full pipeline and compare with examples/expected.json.

Reads all example documents together (like uploading them all), extracts them,
matches them, verifies each invoice, and checks that each scenario produces exactly
the expected link and problems. Nothing is uploaded or stored in the database.

Usage:
    python scripts/check_examples.py
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phase2_documents.reader import read_document  # noqa: E402
from phase3_extraction.extractor import extract  # noqa: E402
from phase4_matching.matcher import find_links  # noqa: E402
from phase5_verification.engine import verify  # noqa: E402
from phase5_verification.models import DocumentRecord  # noqa: E402

EXAMPLES = ROOT / "examples"


def main() -> None:
    expected = json.loads((EXAMPLES / "expected.json").read_text(encoding="utf-8"))
    records: dict[str, DocumentRecord] = {}
    start = time.time()

    for path in sorted(EXAMPLES.glob("*/*")):
        if path.suffix not in {".pdf", ".png", ".docx", ".txt"}:
            continue
        content = read_document(path)
        result = extract(content.text, pages=[p.text for p in content.pages])
        key = f"{path.parent.name}/{path.name}"
        confidences = [p.confidence for p in content.pages if p.confidence is not None]
        records[key] = DocumentRecord(id=result.data.number or key, data=result.data, text=content.text,
                                      evidence=result.evidence, ungrounded=result.ungrounded,
                                      min_ocr_confidence=min(confidences) if confidences else None)
        warn = f"  ungrounded: {result.ungrounded}" if result.ungrounded else ""
        print(f"read {key:<45} {result.data.doc_type:<15} {result.data.number} {result.locale.language} "
              f"{result.data.currency} items={len(result.data.line_items)}{warn}")

    links = {l.invoice: l.purchase_order for l in find_links({k: r.data for k, r in records.items()})}
    print(f"\n{len(records)} documents read in {time.time() - start:.0f}s\n")

    failures = 0
    for case in expected:
        key = f"{case['folder']}/{case['invoice_file']}"
        po_key = links.get(key)
        po = records[po_key] if po_key else None
        problems = sorted({(f.check, f.severity) for f in verify(records[key], po) if f.verdict != "supported"})
        if po is None:
            problems.append(("matching_order", "warning"))  # added by the backend pipeline
        got_po = po.data.number if po else None
        ok = got_po == case["linked_po"] and problems == sorted(map(tuple, case["problems"]))
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {case['folder']:<22} linked to {got_po or '-':<14} problems {problems}"
              + ("" if ok else f"\n       expected linked to {case['linked_po']}, problems {case['problems']}"))

    print(f"\n{len(expected) - failures}/{len(expected)} scenarios behave as documented")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
