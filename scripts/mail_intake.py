"""Import documents attached to emails (optional; nothing is read unless you run this).

    python scripts/mail_intake.py --eml-dir path/to/emails          dry run on saved .eml files
    python scripts/mail_intake.py --eml-dir path/to/emails --apply  import them
    python scripts/mail_intake.py --imap                            dry run on the configured mailbox
    python scripts/mail_intake.py --imap --apply                    import from the mailbox

A dry run (the default) reports what would be imported and changes nothing. The mailbox is
always opened read-only. Settings (.env):

    INTAKE_ORGANIZATION_ID   organization that receives the documents (required)
    INTAKE_UPLOADER_EMAIL    reviewer account recorded as the uploader (required with --apply)
    INTAKE_ALLOWED_SENDERS   comma-separated addresses; empty = accept any sender
    INTAKE_IMAP_HOST, INTAKE_IMAP_PORT (993), INTAKE_IMAP_USER, INTAKE_IMAP_PASSWORD,
    INTAKE_IMAP_FOLDER (INBOX), INTAKE_IMAP_SINCE_DAYS (7)

Run it on a schedule (Windows Task Scheduler, cron, or an n8n "Execute Command" node).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.mail_intake import IntakeConfig, from_directory, from_imap, import_message  # noqa: E402
from db.models import User  # noqa: E402
from db.session import get_session  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--eml-dir", type=Path, help="folder of saved .eml files")
    source.add_argument("--imap", action="store_true", help="read the mailbox configured in .env")
    parser.add_argument("--apply", action="store_true", help="import (default: dry run)")
    args = parser.parse_args()

    org = os.getenv("INTAKE_ORGANIZATION_ID")
    if not org:
        raise SystemExit("Set INTAKE_ORGANIZATION_ID in .env")
    allowed = {a.strip().lower() for a in os.getenv("INTAKE_ALLOWED_SENDERS", "").split(",") if a.strip()}
    messages = from_directory(args.eml_dir) if args.eml_dir else from_imap()

    with get_session() as session:
        uploader = None
        if args.apply:
            email = os.getenv("INTAKE_UPLOADER_EMAIL", "").lower()
            uploader = session.scalar(select(User).where(User.email == email, User.active))
            if uploader is None or uploader.organization_id != int(org) or uploader.role not in ("reviewer", "admin"):
                raise SystemExit("INTAKE_UPLOADER_EMAIL must be an active reviewer or admin of INTAKE_ORGANIZATION_ID")
        config = IntakeConfig(organization_id=int(org), uploader=uploader, allowed_senders=allowed, apply=args.apply)
        for msg in messages:
            print(json.dumps(import_message(session, msg, config), ensure_ascii=False))
    print(f"{len(messages)} email(s) {'processed' if args.apply else 'checked (dry run; add --apply to import)'}")


if __name__ == "__main__":
    main()
