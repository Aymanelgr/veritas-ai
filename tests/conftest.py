"""Shared test setup. pytest loads this file before any test module."""

import os
from pathlib import Path

from dotenv import dotenv_values
import pytest

# Tests always use the separate veritas_test database, never the real one.
# This must run before anything imports db.session (which connects on import).
_env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
if "DATABASE_URL" in _env:
    os.environ["DATABASE_URL"] = _env["DATABASE_URL"] + "_test"
# Tests must not trigger the real n8n workflows (they would post into the real inbox).
os.environ["N8N_WEBHOOK_URL"] = ""


@pytest.fixture(scope="session", autouse=True)
def generated_sample_documents():
    """Create reproducible binary fixtures for a fresh checkout, leaving existing ones alone."""
    samples = Path(__file__).resolve().parent.parent / "data" / "samples"
    generated = ("purchase_order.docx", "purchase_order.pdf", "invoice_scan.png", "invoice_scanned.pdf")
    if any(not (samples / name).exists() for name in generated):
        from phase2_documents.make_samples import main

        main()
