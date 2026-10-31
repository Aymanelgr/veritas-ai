"""Test helpers: create users and signed-in API clients."""

from fastapi.testclient import TestClient

from backend.security import hash_password
from db.models import Organization, User
from db.session import get_session

PASSWORD = "correct-horse-battery"


def make_org(name: str) -> int:
    with get_session() as session:
        org = Organization(name=name)
        session.add(org)
        session.commit()
        return org.id


def make_user(email: str, role: str, organization_id: int = 1) -> None:
    with get_session() as session:
        session.add(User(organization_id=organization_id, email=email, name=email.split("@")[0],
                         role=role, password_hash=hash_password(PASSWORD), active=True))
        session.commit()


def signed_in(app, email: str) -> TestClient:
    # X-Veritas-Client is the header our dashboard sends on every change (CSRF protection).
    client = TestClient(app, headers={"X-Veritas-Client": "test"})
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client
