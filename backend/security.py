"""Passwords, login sessions, roles and request protection.

- Passwords are hashed with scrypt (a slow, salted, memory-hard algorithm from Python's
  standard library), so a stolen database does not reveal them.
- A login creates a random session token sent as an HttpOnly cookie: JavaScript cannot
  read it, and the database stores only its SHA-256 hash.
- Roles are ordered: viewer < reviewer < admin. Each endpoint states the minimum it needs.
- Every request that changes something must carry the X-Veritas-Client header. Browsers
  do not let other websites add custom headers, so this blocks cross-site request forgery.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import User, UserSession

ROLES = {"viewer": 1, "reviewer": 2, "admin": 3}
SESSION_COOKIE = "veritas_session"
SESSION_HOURS = 12
CLIENT_HEADER = "X-Veritas-Client"
MAX_LOGIN_FAILURES = 5  # per email, per 15 minutes
MIN_PASSWORD_LENGTH = 10

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32,
                                   n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token),
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)))
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return token


def user_for_token(db: Session, token: str | None) -> User | None:
    """The active user behind a session token; extends the session while it is used."""
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    now = datetime.now(timezone.utc)
    if session is None or session.expires_at < now or not session.user.active:
        return None
    if session.expires_at - now < timedelta(hours=SESSION_HOURS - 1):
        session.expires_at = now + timedelta(hours=SESSION_HOURS)  # sliding expiry
        db.commit()
    return session.user


def end_session(db: Session, token: str | None) -> None:
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
        if session:
            db.delete(session)
            db.commit()


def has_role(user: User, minimum: str) -> bool:
    return ROLES.get(user.role, 0) >= ROLES[minimum]


def cookie_secure() -> bool:
    """Send the cookie only over HTTPS when deployed (set COOKIE_SECURE=1 behind HTTPS)."""
    return os.getenv("COOKIE_SECURE", "0") == "1"
