"""Check that every tool in the Veritas AI stack is installed and reachable.

Usage:
    python scripts/check_setup.py
"""

import importlib
import socket

import httpx

PACKAGES = [
    "nltk", "textstat", "pymupdf", "docx", "paddleocr", "spacy", "pydantic",
    "torch", "transformers", "sentence_transformers", "fastapi", "sqlalchemy",
    "psycopg", "pgvector", "redis", "rq", "ollama", "pytest", "sklearn",
]

SERVICES = {"PostgreSQL": 5432, "Redis": 6379, "n8n": 5678, "Ollama": 11434}


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if ok else 'FAIL'}] {name} {detail}")
    return ok


def main() -> None:
    results = []

    print("Python packages:")
    for name in PACKAGES:
        try:
            module = importlib.import_module(name)
            results.append(check(name, True, getattr(module, "__version__", "")))
        except Exception as error:
            results.append(check(name, False, f"-> {error}"))

    print("\nGPU:")
    import torch
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "not available"
    results.append(check("CUDA", torch.cuda.is_available(), gpu))

    print("\nLanguage data:")
    import nltk
    import spacy
    for resource in ["tokenizers/punkt_tab", "corpora/stopwords"]:
        try:
            nltk.data.find(resource)
            results.append(check(f"nltk {resource}", True))
        except LookupError:
            results.append(check(f"nltk {resource}", False))
    try:
        spacy.load("en_core_web_sm")
        results.append(check("spaCy en_core_web_sm", True))
    except OSError:
        results.append(check("spaCy en_core_web_sm", False))

    print("\nServices:")
    for name, port in SERVICES.items():
        with socket.socket() as s:
            s.settimeout(2)
            results.append(check(name, s.connect_ex(("localhost", port)) == 0, f"localhost:{port}"))
    try:
        models = [m["name"] for m in httpx.get("http://localhost:11434/api/tags").json()["models"]]
        results.append(check("Ollama models", bool(models), ", ".join(models)))
    except Exception as error:
        results.append(check("Ollama models", False, f"-> {error}"))

    print(f"\n{sum(results)}/{len(results)} checks passed.")


if __name__ == "__main__":
    main()
