"""The assistant: questions about documents (RAG) and about the work queue (database), with
saved conversations. Everything is restricted to the user's organization, and a conversation
is visible only to the user who started it.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import schemas, structured
from backend.deps import db, owned_document, require
from db.models import Conversation, ConversationMessage, Document, User
from phase3_extraction import llm
from phase6_rag.rag import ask

router = APIRouter(prefix="/api", tags=["assistant"])
MAX_QUESTION = 1000


def _owned_conversation(session: Session, user: User, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.organization_id != user.organization_id:
        raise HTTPException(404, "Conversation not found")
    return conversation


def _scope(session: Session, user: User, document_ids: list[int]) -> list[int]:
    """Documents the user may search. Documents deleted since the conversation began are dropped."""
    if not document_ids:
        return []
    allowed = set(session.scalars(select(Document.id).where(
        Document.id.in_(document_ids), Document.organization_id == user.organization_id)))
    return [i for i in document_ids if i in allowed]


def forget_document(session: Session, organization_id: int, document_id: int) -> None:
    """Remove a deleted document's passages from saved answers (deletion and retention mean gone)."""
    for message in session.scalars(select(ConversationMessage).join(Conversation).where(
            Conversation.organization_id == organization_id)):
        answer = message.answer or {}
        sources = answer.get("sources", [])
        records = answer.get("records", [])
        if any(x.get("document_id") == document_id for x in [*sources, *records]):
            message.answer = {**answer,
                              "sources": [x for x in sources if x.get("document_id") != document_id],
                              "records": [x for x in records if x.get("document_id") != document_id],
                              "redacted": True}


@router.post("/ask")
def ask_question(body: schemas.AskIn, user: User = Depends(require("viewer")),
                 session: Session = Depends(db)) -> dict:
    question = body.question.strip()[:MAX_QUESTION]
    if not question:
        raise HTTPException(422, "Ask a question")
    for document_id in body.document_ids or []:
        owned_document(session, user, document_id)  # 404 for anything outside the organization

    if body.conversation_id is not None:
        conversation = _owned_conversation(session, user, body.conversation_id)
        if body.document_ids is not None:
            conversation.document_ids = body.document_ids
    else:
        conversation = Conversation(organization_id=user.organization_id, user_id=user.id, title=question[:200],
                                    document_ids=body.document_ids or [])
        session.add(conversation)
        session.flush()
    scope = _scope(session, user, conversation.document_ids or [])

    # Counts and statuses come from the database (exact); content questions from the documents (RAG).
    result = structured.answer(session, user.organization_id, question, scope or None)
    if result is None:
        if not llm.is_available():
            raise HTTPException(503, "The local LLM (Ollama) is not running, so questions about document "
                                     "content cannot be answered right now.")
        history = [(m.question, m.answer.get("answer", "")) for m in conversation.messages
                   if m.answer.get("kind") == "documents"]
        rag = ask(session, question, document_ids=scope or None, organization_id=user.organization_id,
                  history=history)
        result = {**rag.model_dump(mode="json"), "kind": "documents"}
        result["unsupported"] = (not rag.sources) or (rag.citation_accuracy is not None and rag.citation_accuracy < 1)
    result = {"question": question, "sources": [], "checks": [], "citation_accuracy": None, "records": [], **result,
              "conversation_id": conversation.id, "scope": scope}
    session.add(ConversationMessage(conversation_id=conversation.id, question=question, answer=result))
    conversation.updated_at = datetime.now(timezone.utc)
    session.commit()
    return result


@router.get("/conversations")
def list_conversations(user: User = Depends(require("viewer")),
                       session: Session = Depends(db)) -> list[schemas.ConversationOut]:
    rows = session.scalars(select(Conversation).where(
        Conversation.user_id == user.id, Conversation.organization_id == user.organization_id)
        .order_by(Conversation.updated_at.desc().nullslast(), Conversation.id.desc()).limit(50))
    return [schemas.ConversationOut.model_validate(c) for c in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(require("viewer")),
                     session: Session = Depends(db)) -> schemas.ConversationDetail:
    c = _owned_conversation(session, user, conversation_id)
    # Sources from documents deleted since are removed, so nothing deleted is shown again.
    alive = set(session.scalars(select(Document.id).where(Document.organization_id == user.organization_id)))
    messages = []
    for m in c.messages:
        answer = dict(m.answer)
        answer["sources"] = [s for s in answer.get("sources", []) if s.get("document_id") in alive]
        answer["records"] = [r for r in answer.get("records", []) if r.get("document_id") in alive]
        messages.append(schemas.ConversationTurn(question=m.question, answer=answer, created_at=m.created_at))
    return schemas.ConversationDetail(**schemas.ConversationOut.model_validate(c).model_dump(), messages=messages)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(require("viewer")),
                        session: Session = Depends(db)) -> None:
    session.delete(_owned_conversation(session, user, conversation_id))
    session.commit()
