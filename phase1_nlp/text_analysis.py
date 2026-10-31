"""Phase 1 - Text analysis script for Veritas AI.

Reads one or more text documents and reports:
  - basic statistics (sentences, words, unique words)
  - the most frequent meaningful words (NLTK)
  - key facts found with regular expressions (references, dates, amounts, emails)
  - readability scores (textstat)

Usage:
    python phase1_nlp/text_analysis.py data/samples/purchase_order.txt data/samples/invoice.txt
    python phase1_nlp/text_analysis.py data/samples/invoice.txt --json
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import textstat
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize

STOPWORDS = set(stopwords.words("english"))

# Each pattern targets one kind of fact the verification engine will need later.
# All groups are non-capturing (?:...) so findall() returns the whole match.
PATTERNS = {
    "references": re.compile(r"\b(?:PO|INV)-\d{4}-\d{3,}\b"),
    "dates": re.compile(
        r"\b\d{4}-\d{2}-\d{2}\b"  # 2026-10-01
        r"|\b\d{1,2}/\d{1,2}/\d{4}\b"  # 11/17/2026
        r"|\b(?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December) \d{1,2}, \d{4}\b"  # October 20, 2026
    ),
    "amounts": re.compile(r"[$€£]\s?\d+(?:,\d{3})*(?:\.\d{2})?"),
    "emails": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
}


def analyze(text: str) -> dict:
    sentences = sent_tokenize(text)
    tokens = word_tokenize(text)
    # Keep real words only: drop punctuation and numbers, ignore case.
    words = [t.lower() for t in tokens if t.isalpha()]
    content_words = [w for w in words if w not in STOPWORDS]

    return {
        "stats": {
            "characters": len(text),
            "sentences": len(sentences),
            "words": len(words),
            "unique_words": len(set(words)),
        },
        "top_words": Counter(content_words).most_common(10),
        # dict.fromkeys removes duplicates while keeping order of appearance.
        "facts": {name: list(dict.fromkeys(p.findall(text))) for name, p in PATTERNS.items()},
        "readability": {
            "flesch_reading_ease": textstat.flesch_reading_ease(text),
            "flesch_kincaid_grade": textstat.flesch_kincaid_grade(text),
            "difficult_words": textstat.difficult_words(text),
        },
    }


def print_report(path: Path, result: dict) -> None:
    stats = result["stats"]
    print(f"\n=== {path.name} ===")
    print(
        f"Sentences: {stats['sentences']} | Words: {stats['words']} "
        f"| Unique words: {stats['unique_words']}"
    )

    print("\nTop words:")
    for word, count in result["top_words"]:
        print(f"  {word:<15} {count}")

    print("\nExtracted facts:")
    for name, values in result["facts"].items():
        print(f"  {name:<11} {', '.join(values) or '-'}")

    r = result["readability"]
    print(
        f"\nReadability: Flesch ease {r['flesch_reading_ease']:.1f}, "
        f"grade level {r['flesch_kincaid_grade']:.1f}, "
        f"difficult words {r['difficult_words']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze text documents.")
    parser.add_argument("files", nargs="+", type=Path, help="text files to analyze")
    parser.add_argument("--json", action="store_true", help="print results as JSON")
    args = parser.parse_args()

    results = {str(path): analyze(path.read_text(encoding="utf-8")) for path in args.files}

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for path in args.files:
            print_report(path, results[str(path)])


if __name__ == "__main__":
    main()
