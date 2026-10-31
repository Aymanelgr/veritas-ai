"""Shared request dependencies: database session, signed-in user, role checks, ownership.

Every endpoint that touches data goes through `require(...)` and the `owned_*` helpers,
so organization boundaries are enforced in one place instead of being re-implemented
(and possibly forgotten) in each endpoint.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.security import SESSION_COOKIE, has_role, user_for_token
from db.models import Document, Finding, User
from db.session import get_session


def db():
    """One database session per request, always closed afterwards."""
    with get_session() as session:
        yield session


def current_user(request: Request, session: Session = Depends(db)) -> User:
    user = user_for_token(session, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Please sign in")
    return user


def require(role: str):
    """Dependency factory: require(\"reviewer\") lets reviewers and admins through."""

    def check(user: User = Depends(current_user)) -> User:
        if not has_role(user, role):
            raise HTTPException(403, f"This action needs the {role} role")
        return user

    return check


def owned_document(session: Session, user: User, document_id: int) -> Document:
    """A document of the user's organization. Others answer 404, not 403, so their existence is not revealed."""
    doc = session.get(Document, document_id)
    if doc is None or doc.organization_id != user.organization_id:
        raise HTTPException(404, "Document not found")
    return doc


def owned_finding(session: Session, user: User, finding_id: int) -> Finding:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, "Finding not found")
    owned_document(session, user, finding.document_id)
    return finding
