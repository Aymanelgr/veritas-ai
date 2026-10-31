"""Veritas AI REST API.

Usage (from the project root):
    uvicorn backend.main:app --port 8000
    then open http://localhost:8000/docs for interactive API documentation.

The endpoints live in backend/routers/ (one file per topic). Every one of them
requires a signed-in user with a sufficient role, and only sees that user's
organization (see backend/deps.py).
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend import schemas
from backend.deps import db, require
from backend.jobs import redis
from backend.routers import admin, assistant, auth, automation, documents, findings, links, notifications
from backend.routers.documents import UPLOAD_DIR
from backend.security import CLIENT_HEADER
from db.models import Document, Finding, User
from db.session import init_db
from phase3_extraction import llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # applies pending database migrations
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Veritas AI", version="0.2.0", lifespan=lifespan)
# The React dev server runs on another port; browsers block cross-origin calls unless allowed.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_client_header(request: Request, call_next):
    """Cross-site request forgery protection.

    A malicious website can make a visitor's browser send a POST to Veritas (with their
    cookie), but it cannot add custom headers. Our own dashboard always sends
    X-Veritas-Client; n8n authenticates with X-Veritas-Token instead.
    """
    changes_state = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    if (changes_state and request.url.path.startswith("/api/")
            and not request.headers.get(CLIENT_HEADER) and not request.headers.get("X-Veritas-Token")):
        return JSONResponse({"detail": f"Missing {CLIENT_HEADER} header"}, status_code=403)
    return await call_next(request)


for module in (auth, documents, findings, links, assistant, notifications, admin, automation):
    app.include_router(module.router)


@app.get("/api/health")
def health(session: Session = Depends(db)) -> dict:
    """Service status only, no data, so it needs no sign-in."""
    session.execute(select(1))
    return {"database": True, "redis": bool(redis.ping()), "llm": llm.is_available()}


@app.get("/api/stats")
def stats(user: User = Depends(require("viewer")), session: Session = Depends(db)) -> schemas.Stats:
    org = user.organization_id

    def count_documents(*conditions) -> int:
        return session.scalar(select(func.count()).select_from(Document)
                              .where(Document.organization_id == org, *conditions))

    def count_findings(*conditions) -> int:
        return session.scalar(select(func.count()).select_from(Finding)
                              .join(Document, Finding.document_id == Document.id)
                              .where(Document.organization_id == org, *conditions))

    return schemas.Stats(
        documents=count_documents(),
        processing=count_documents(Document.status.in_(["uploaded", "processing"])),
        failed=count_documents(Document.status == "failed"),
        pending_reviews=count_findings(Finding.review_status == "pending"),
        critical_open=count_findings(Finding.review_status == "pending", Finding.severity == "critical"),
        approved=count_findings(Finding.review_status == "approved"),
        rejected=count_findings(Finding.review_status == "rejected"),
    )
