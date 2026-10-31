"""Answer operational questions ("how many invoices have open issues?") from the database.

Counts, statuses and amounts must be exact, so they come from SQL, never from a language
model reading passages. A question is answered here only when it clearly matches one of the
known question types (English or French); anything else goes to document search (RAG).
"""

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Document, Finding, Link

COUNT = r"(how many|number of|count|combien|nombre)"
DOCS = r"\b(documents?|invoices?|factures?|purchase orders?|orders?|bons? de commande|commandes?)\b"
# The question must be ABOUT the work queue (documents, findings, matches), not about a document's content.
ABOUT = re.compile(DOCS[:-3] + r"|findings?|issues?|problems?|problèmes?|anomalies?|reviews?|matche?s?|links?)\b"
                   r"|amount at stake|montant", re.I)
PATTERNS = [  # (name, regex); the first match wins
    ("failed", re.compile(r"\b(fail|failed|failing|errors?|échou\w*|en erreur)\b", re.I)),
    ("unmatched", re.compile(r"(unmatched|not (been )?matched|without (a |an )?(purchase )?order|no (purchase )?order|"
                             r"sans bon de commande|non rapproch|pas de bon de commande)", re.I)),
    ("ambiguous", re.compile(r"\b(ambiguous|ambigu\w*)\b", re.I)),
    ("at_stake", re.compile(r"(amount|money|total) (at stake|at risk|in dispute)|montant (en jeu|en litige|à risque)", re.I)),
    ("pending", re.compile(r"(pending|awaiting|waiting for|to review|need(s)? review|open (issue|finding|problem)s?|"
                           r"unresolved|à (re)?voir|en attente|non résolu|problèmes? ouverts?)", re.I)),
    ("processing", re.compile(r"\b(being processed|in progress|queued|en cours)\b", re.I)),
    ("documents", re.compile(COUNT + r".*" + DOCS, re.I)),
    ("overview", re.compile(r"^(status|overview|summary|résumé|état|situation)\b|^(give me|show me) (a |an )?(status|overview|summary)",
                            re.I)),
]
TYPES = [("invoice", re.compile(r"\b(invoices?|factures?)\b", re.I)),
         ("purchase_order", re.compile(r"\b(purchase orders?|orders?|bons? de commande|commandes?)\b", re.I))]
MAX_LISTED = 15


def _label(d: Document) -> str:
    return f"{(d.doc_type or 'document').replace('_', ' ')} {d.number or d.filename}"


def _row(d: Document, detail: str = "") -> dict:
    return {"document_id": d.id, "label": _label(d), "detail": detail}


def classify(question: str) -> str | None:
    q = question.strip()
    for name, pattern in PATTERNS:
        if pattern.search(q):
            # "pending"/"failed" etc. only count as database questions when phrased as one,
            # so "what does the pending clause say?" still goes to document search.
            if name in ("pending", "failed", "processing", "unmatched", "ambiguous", "at_stake") and not (
                    ABOUT.search(q) and re.search(COUNT + r"|^(which|what|list|show|is|are|any|quel|quels|quelles|"
                                                  r"liste|montre|y a)|\?$", q, re.I)):
                continue
            return name
    return None


def answer(session: Session, organization_id: int, question: str, document_ids: list[int] | None = None) -> dict | None:
    kind = classify(question)
    if kind is None:
        return None
    docs_q = select(Document).where(Document.organization_id == organization_id)
    if document_ids:
        docs_q = docs_q.where(Document.id.in_(document_ids))
    doc_type = next((t for t, p in TYPES if p.search(question)), None)
    rows: list[dict] = []

    def open_findings():
        q = (select(Finding, Document).join(Document, Finding.document_id == Document.id)
             .where(Document.organization_id == organization_id, Finding.review_status == "pending"))
        if document_ids:
            q = q.where(Document.id.in_(document_ids))
        return session.execute(q).all()

    if kind == "documents":
        q = docs_q.where(Document.duplicate_of_id.is_(None))
        if doc_type:
            q = q.where(Document.doc_type == doc_type)
        docs = session.scalars(q).all()
        by_status: dict[str, int] = {}
        for d in docs:
            by_status[d.status] = by_status.get(d.status, 0) + 1
        what = {"invoice": "invoice", "purchase_order": "purchase order"}.get(doc_type, "document")
        text = f"There {'is' if len(docs) == 1 else 'are'} {len(docs)} {what}{'' if len(docs) == 1 else 's'}"
        text += (" (" + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())) + ")." if docs else ".")
        text += " Duplicate uploads are not counted."
    elif kind == "pending":
        found = open_findings()
        if doc_type:
            found = [(f, d) for f, d in found if d.doc_type == doc_type]
        severity: dict[str, int] = {}
        per_doc: dict[int, tuple[Document, list]] = {}
        for f, d in found:
            severity[f.severity] = severity.get(f.severity, 0) + 1
            per_doc.setdefault(d.id, (d, []))[1].append(f)
        text = (f"{len(found)} finding{'s' if len(found) != 1 else ''} await review on {len(per_doc)} document"
                f"{'s' if len(per_doc) != 1 else ''}")
        text += (" (" + ", ".join(f"{n} {s}" for s, n in sorted(severity.items())) + ")." if found else ".")
        rows = [_row(d, f"{len(fs)} open: " + "; ".join(f.claim for f in fs[:2]))
                for d, fs in sorted(per_doc.values(), key=lambda x: -len(x[1]))]
    elif kind == "failed":
        docs = session.scalars(docs_q.where(Document.status == "failed")).all()
        text = f"{len(docs)} document{'s' if len(docs) != 1 else ''} failed to process."
        rows = [_row(d, (d.error or "")[:160]) for d in docs]
    elif kind == "processing":
        docs = session.scalars(docs_q.where(Document.status.in_(["uploaded", "processing"]))).all()
        text = f"{len(docs)} document{'s are' if len(docs) != 1 else ' is'} waiting or being processed."
        rows = [_row(d, d.stage or d.status) for d in docs]
    elif kind in ("unmatched", "ambiguous"):
        invoices = session.scalars(docs_q.where(Document.doc_type == "invoice", Document.is_current,
                                                Document.duplicate_of_id.is_(None))).all()
        statuses: dict[int, set[str]] = {}
        if invoices:
            for link in session.scalars(select(Link).where(Link.invoice_id.in_([i.id for i in invoices]))):
                statuses.setdefault(link.invoice_id, set()).add(link.status)
        if kind == "ambiguous":
            hits = [i for i in invoices if "ambiguous" in statuses.get(i.id, set())]
            text = f"{len(hits)} invoice{'s have' if len(hits) != 1 else ' has'} an ambiguous match waiting for a person."
        else:
            hits = [i for i in invoices if not statuses.get(i.id, set()) & {"proposed", "confirmed"}]
            text = (f"{len(hits)} of {len(invoices)} current invoices {'are' if len(hits) != 1 else 'is'} not matched "
                    "to a purchase order (including ambiguous or conflicting matches).")
        rows = [_row(i, ", ".join(sorted(statuses.get(i.id, {"no candidate"})))) for i in hits]
    elif kind == "at_stake":
        totals: dict[str, Decimal] = {}
        unknown = 0
        for f, _ in open_findings():
            if f.kind != "discrepancy" or f.impact is None:
                continue
            if f.currency:
                totals[f.currency] = totals.get(f.currency, Decimal(0)) + abs(f.impact)
            else:
                unknown += 1
        if totals:
            text = "Open discrepancies with a computed amount: " + ", ".join(
                f"{v:,.2f} {c}" for c, v in sorted(totals.items())) + ". Amounts in different currencies are not added up."
        else:
            text = "No open discrepancy has a computed amount."
        if unknown:
            text += f" {unknown} more could not be valued because the currency is unknown."
    else:  # overview
        docs = session.scalars(docs_q.where(Document.duplicate_of_id.is_(None))).all()
        found = open_findings()
        critical = sum(f.severity == "critical" for f, _ in found)
        failed = sum(d.status == "failed" for d in docs)
        busy = sum(d.status in ("uploaded", "processing") for d in docs)
        text = (f"{len(docs)} documents ({sum(d.doc_type == 'invoice' for d in docs)} invoices, "
                f"{sum(d.doc_type == 'purchase_order' for d in docs)} purchase orders). {len(found)} findings await "
                f"review, {critical} critical. {failed} failed, {busy} in progress.")
    if document_ids:
        text += " (Limited to the documents selected for this conversation.)"
    listed = rows[:MAX_LISTED]
    if len(rows) > MAX_LISTED:
        text += f" The first {MAX_LISTED} are listed."
    return {"answer": text, "kind": "database", "records": listed}
