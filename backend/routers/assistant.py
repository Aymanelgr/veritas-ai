"""Questions about documents (RAG), restricted to the user's organization."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import schemas
from backend.deps import db, owned_document, require
from db.models import User
from phase3_extraction import llm
from phase6_rag.rag import RagAnswer, ask

router = APIRouter(prefix="/api", tags=["assistant"])


@router.post("/ask")
def ask_question(body: schemas.AskIn, user: User = Depends(require("viewer")),
                 session: Session = Depends(db)) -> RagAnswer:
    if not llm.is_available():
        raise HTTPException(503, "The local LLM (Ollama) is not running")
    for document_id in body.document_ids or []:
        owned_document(session, user, document_id)  # 404 for anything outside the organization
    return ask(session, body.question, document_ids=body.document_ids, organization_id=user.organization_id)
