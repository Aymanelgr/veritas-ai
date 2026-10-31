"""Rebuild search passages made by a different embedding model than the current one.

Vectors from different models cannot be compared, so after changing EMBEDDING_MODEL the
old passages are invisible to search until they are re-embedded. Only documents whose
passages use another model are processed; nothing else changes.

Usage (from the project root):
    python scripts/reindex.py
"""

import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.models import Chunk, Document  # noqa: E402
from db.session import get_session, init_db  # noqa: E402
from phase4_matching.matcher import EMBEDDING_MODEL  # noqa: E402
from phase6_rag.rag import index_document  # noqa: E402


def main() -> None:
    init_db()
    with get_session() as session:
        stale = session.scalars(select(Document).where(Document.id.in_(
            select(Chunk.document_id).where(Chunk.embedding_model != EMBEDDING_MODEL)))).all()
        for doc in stale:
            pages = {}
            for chunk in sorted(doc.chunks, key=lambda c: c.position):
                pages.setdefault(chunk.page, []).append(chunk.text)
            index_document(doc, [(page, "\n\n".join(texts)) for page, texts in sorted(pages.items())])
            session.commit()
            print(f"re-indexed #{doc.id} {doc.filename}: {len(doc.chunks)} passages")
    print(f"{len(stale)} document(s) re-indexed with {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()
