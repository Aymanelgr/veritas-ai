"""Administration from the command line (the first admin cannot be created from the website).

Usage (from the project root):
    python -m backend.manage create-user --email you@example.com --name "Your Name" --role admin
    python -m backend.manage create-org --name "Second Company"
    python -m backend.manage list-users

The password is asked interactively (not echoed), or read from the environment variable
named by --password-env, so it never appears in your shell history.
"""

import argparse
import getpass
import os

from sqlalchemy import func, select

from backend.audit import record
from backend.security import ROLES, hash_password, password_problem
from db.models import Organization, User
from db.session import get_session, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Veritas AI administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=list(ROLES), default="reviewer")
    create.add_argument("--org", type=int, default=1, help="organization id (default 1)")
    create.add_argument("--password-env", help="read the password from this environment variable")
    org = sub.add_parser("create-org")
    org.add_argument("--name", required=True)
    sub.add_parser("list-users")
    args = parser.parse_args()

    init_db()
    with get_session() as session:
        if args.command == "create-org":
            organization = Organization(name=args.name)
            session.add(organization)
            session.commit()
            print(f"Created organization {organization.id}: {organization.name}")
        elif args.command == "list-users":
            for user in session.scalars(select(User).order_by(User.organization_id, User.id)):
                print(f"{user.id:>3}  org {user.organization_id}  {user.role:<8} "
                      f"{'active ' if user.active else 'disabled'}  {user.email}")
        else:
            email = args.email.strip().lower()
            if session.scalar(select(User).where(func.lower(User.email) == email)):
                raise SystemExit(f"A user with email {email} already exists")
            if session.get(Organization, args.org) is None:
                raise SystemExit(f"Organization {args.org} does not exist")
            password = os.environ.get(args.password_env, "") if args.password_env else getpass.getpass("Password: ")
            if problem := password_problem(password):
                raise SystemExit(problem)
            user = User(organization_id=args.org, email=email, name=args.name, role=args.role,
                        password_hash=hash_password(password), active=True)
            session.add(user)
            session.flush()
            record(session, None, "user_created", "user", user.id, organization_id=args.org,
                   email=email, role=args.role, via="command line")
            session.commit()
            print(f"Created {args.role} {email} in organization {args.org}")


if __name__ == "__main__":
    main()
