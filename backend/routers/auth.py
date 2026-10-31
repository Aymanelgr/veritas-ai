"""Sign in, sign out, and "who am I"."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.audit import record
from backend.deps import current_user, db
from backend.jobs import redis
from backend.security import (
    MAX_LOGIN_FAILURES, SESSION_COOKIE, SESSION_HOURS, cookie_secure, create_session, end_session,
    hash_password, password_problem, verify_password,
)
from db.models import Organization, User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(session: Session, user: User) -> schemas.UserOut:
    org = session.get(Organization, user.organization_id)
    return schemas.UserOut.model_validate(user).model_copy(update={"organization_name": org.name if org else None})


@router.post("/login")
def login(body: schemas.LoginIn, request: Request, response: Response,
          session: Session = Depends(db)) -> schemas.UserOut:
    email = body.email.strip().lower()
    # Slow down password guessing: after 5 failures, this email is locked for 15 minutes.
    failures_key = f"login-failures:{email}"
    if int(redis.get(failures_key) or 0) >= MAX_LOGIN_FAILURES:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")

    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        redis.incr(failures_key)
        redis.expire(failures_key, 15 * 60)
        record(session, user, "login_failed", organization_id=user.organization_id if user else None,
               email=email, ip=request.client.host if request.client else None)
        session.commit()
        # The same message for "no such user" and "wrong password", so accounts can't be probed.
        raise HTTPException(401, "Wrong email or password")

    redis.delete(failures_key)
    token = create_session(session, user)
    record(session, user, "login", ip=request.client.host if request.client else None)
    session.commit()
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        samesite="lax", secure=cookie_secure(), path="/")
    return user_out(session, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(db)) -> None:
    end_session(session, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/password", status_code=204)
def change_password(body: schemas.PasswordChangeIn, request: Request, user: User = Depends(current_user),
                    session: Session = Depends(db)) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "The current password is wrong")
    if problem := password_problem(body.new_password):
        raise HTTPException(422, problem)
    user.password_hash = hash_password(body.new_password)
    # Sign out every other browser: a changed password should cut off anyone who knew the old one.
    current = request.cookies.get(SESSION_COOKIE)
    for other in session.scalars(select(UserSession).where(UserSession.user_id == user.id)):
        if current is None or other.token_hash != hashlib.sha256(current.encode()).hexdigest():
            session.delete(other)
    record(session, user, "password_changed", "user", user.id)
    session.commit()


@router.get("/me")
def me(user: User = Depends(current_user), session: Session = Depends(db)) -> schemas.UserOut:
    return user_out(session, user)
