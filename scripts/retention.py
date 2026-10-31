"""Delete documents older than a retention period (configurable data retention).

    python scripts/retention.py --days 365            show what WOULD be deleted (dry run)
    python scripts/retention.py --days 365 --apply    delete them

Deleting a document removes its file, text, passages, links and findings. Each deletion
is written to the audit history (without the document's content). Set RETENTION_DAYS
in .env to make --days optional. Documents with unresolved findings are kept unless
--include-open is given, so nothing awaiting review disappears silently.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import exists, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.audit import record  # noqa: E402
from backend.routers.assistant import forget_document  # noqa: E402
from db.models import Document, Finding  # noqa: E402
from db.session import get_session  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=int(os.getenv("RETENTION_DAYS", "0")) or None)
    parser.add_argument("--apply", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument("--include-open", action="store_true", help="also delete documents with pending findings")
    args = parser.parse_args()
    if not args.days:
        raise SystemExit("Give --days N or set RETENTION_DAYS in .env")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    with get_session() as session:
        query = select(Document).where(Document.created_at < cutoff)
        if not args.include_open:
            open_findings = exists().where(Finding.document_id == Document.id, Finding.review_status == "pending")
            query = query.where(~open_findings)
        docs = session.scalars(query).all()
        for doc in docs:
            print(f"{'deleting' if args.apply else 'would delete'} #{doc.id} {doc.filename} "
                  f"(uploaded {doc.created_at:%Y-%m-%d})")
            if args.apply:
                record(session, None, "document_deleted_by_retention", "document", doc.id,
                       organization_id=doc.organization_id, filename=doc.filename, retention_days=args.days)
                forget_document(session, doc.organization_id, doc.id)  # also from saved assistant answers
                Path(doc.file_path).unlink(missing_ok=True)
                session.delete(doc)
        session.commit()
    print(f"{len(docs)} document(s) {'deleted' if args.apply else 'would be deleted (dry run; add --apply)'}")


if __name__ == "__main__":
    main()
