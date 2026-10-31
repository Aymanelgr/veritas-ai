"""Administration: users of the organization and the audit history."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.audit import record
from backend.deps import db, require
from backend.routers.auth import user_out
from backend.security import hash_password, password_problem
from db.models import AuditEvent, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(admin: User = Depends(require("admin")), session: Session = Depends(db)) -> list[schemas.UserOut]:
    users = session.scalars(select(User).where(User.organization_id == admin.organization_id).order_by(User.id))
    return [user_out(session, u) for u in users]


@router.post("/users", status_code=201)
def create_user(body: schemas.UserCreateIn, admin: User = Depends(require("admin")),
                session: Session = Depends(db)) -> schemas.UserOut:
    email = body.email.strip().lower()
    if problem := password_problem(body.password):
        raise HTTPException(422, problem)
    if session.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with this email already exists")
    user = User(organization_id=admin.organization_id, email=email, name=body.name.strip(),
                password_hash=hash_password(body.password), role=body.role, active=True)
    session.add(user)
    session.flush()
    record(session, admin, "user_created", "user", user.id, email=email, role=body.role)
    session.commit()
    return user_out(session, user)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: schemas.UserUpdateIn, admin: User = Depends(require("admin")),
                session: Session = Depends(db)) -> schemas.UserOut:
    user = session.get(User, user_id)
    if user is None or user.organization_id != admin.organization_id:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and (body.role not in (None, "admin") or body.active is False):
        raise HTTPException(422, "You cannot remove your own admin access")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    record(session, admin, "user_updated", "user", user.id, **changes)
    session.commit()
    return user_out(session, user)


@router.get("/audit")
def audit_history(limit: int = 100, admin: User = Depends(require("admin")),
                  session: Session = Depends(db)) -> list[schemas.AuditOut]:
    rows = session.execute(
        select(AuditEvent, User.email).outerjoin(User, AuditEvent.user_id == User.id)
        .where(AuditEvent.organization_id == admin.organization_id)
        .order_by(AuditEvent.created_at.desc()).limit(min(limit, 500)))
    return [schemas.AuditOut.model_validate(e).model_copy(update={"user_email": email}) for e, email in rows]
