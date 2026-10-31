"""Help for reviewers: explain a finding, say what evidence would settle it, draft a message to
the supplier, show a transaction's timeline, and simulate corrections.

All of this is deterministic (built from stored findings, evidence and history, not generated
by a model), so it cannot invent facts, and none of it changes documents, findings or links.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from db.models import AlertDelivery, AuditEvent, Correction, Document, Finding, Link, ProcessingRun, User
from phase3_extraction.schemas import Extraction

USABLE_LINKS = ("proposed", "confirmed")  # same as backend.pipeline, which is imported lazily (it loads OCR)

# What would settle each kind of finding. Reviewers attach it with "Attach evidence".
RESOLVE = {
    "quantity_match": ["A credit note for the extra quantity",
                       "The buyer's written approval of the new quantity",
                       "A delivery note or goods receipt showing the quantity actually received"],
    "cumulative_quantity": ["The earlier invoices for this order, to rule out double billing",
                            "A credit note for the quantity billed beyond the order",
                            "An amended order raising the ordered quantity"],
    "unit_price_match": ["An amended order or price agreement with the new price",
                         "A credit note for the price difference"],
    "unexpected_item": ["An order amendment adding this item", "A credit note removing it from the invoice"],
    "unit_match": ["The conversion between the ordered and invoiced units, confirmed by the supplier"],
    "currency_match": ["The currency of each document (set it under Reading settings)",
                       "Contract terms stating the billing currency"],
    "matching_order": ["The purchase order this invoice refers to (upload it, or link it by hand)"],
    "line_arithmetic": ["A corrected invoice from the supplier"],
    "subtotal_arithmetic": ["A corrected invoice from the supplier"],
    "total_arithmetic": ["A corrected invoice, or the missing adjustment (discount, shipping, credit) explained"],
    "tax_rate": ["Confirmation of the applicable tax rate for this purchase"],
    "date_order": ["Confirmation of the order and invoice dates (a typo or a back-dated invoice)"],
    "delivery_deadline": ["The delivery note with the actual delivery date",
                          "The buyer's agreement to the later delivery"],
}
KIND_SUMMARY = {
    "discrepancy": "The documents disagree. This is a difference between what was ordered and what was billed, "
                   "or within the invoice itself.",
    "possible_reading_error": "This may be a reading problem rather than a real difference: a value involved was "
                              "not found in the document text or was read with low confidence. Check the original "
                              "and correct the value if it was misread.",
    "not_checked": "This check could not run, so nothing is known yet either way. It is not a pass.",
    "ok": "This check passed.",
}

# Field names in clarification drafts.
FIELD_LABELS = {
    "en": {"quantity": "quantity", "unit_price": "unit price", "total": "total", "currency": "currency",
           "description": "item", "issue_date": "date", "delivery_date": "delivery date", "tax": "tax",
           "subtotal": "subtotal", "amount": "amount"},
    "fr": {"quantity": "quantité", "unit_price": "prix unitaire", "total": "total", "currency": "devise",
           "description": "article", "issue_date": "date", "delivery_date": "date de livraison", "tax": "taxe",
           "subtotal": "sous-total", "amount": "montant"},
    "ar": {"quantity": "الكمية", "unit_price": "سعر الوحدة", "total": "المجموع", "currency": "العملة",
           "description": "البند", "issue_date": "التاريخ", "delivery_date": "تاريخ التسليم", "tax": "الضريبة",
           "subtotal": "المجموع الفرعي", "amount": "المبلغ"},
}
TEMPLATES = {
    "en": {
        "subject": "Question about invoice {invoice}",
        "greeting": "Hello{supplier},",
        "intro": "While checking invoice {invoice}{order} we found a point we would like to clarify:",
        "ask": "Could you please confirm the correct figures and, if the invoice is wrong, send a corrected "
               "invoice or a credit note?",
        "close": "Thank you,\n{name}",
    },
    "fr": {
        "subject": "Question concernant la facture {invoice}",
        "greeting": "Bonjour{supplier},",
        "intro": "Lors de la vérification de la facture {invoice}{order}, nous avons relevé un point à clarifier :",
        "ask": "Pourriez-vous confirmer les montants corrects et, si la facture est erronée, nous adresser une "
               "facture rectificative ou un avoir ?",
        "close": "Merci d'avance,\n{name}",
    },
    "ar": {
        "subject": "استفسار بخصوص الفاتورة {invoice}",
        "greeting": "السلام عليكم{supplier}،",
        "intro": "أثناء مراجعة الفاتورة {invoice}{order} لاحظنا نقطة نود توضيحها:",
        "ask": "نرجو تأكيد الأرقام الصحيحة، وفي حال وجود خطأ في الفاتورة، إرسال فاتورة مصححة أو إشعار دائن.",
        "close": "مع الشكر،\n{name}",
    },
}
ORDER_PHRASE = {"en": " (order {order})", "fr": " (bon de commande {order})", "ar": " (أمر الشراء {order})"}


def _field_name(path: str) -> str:
    return path.split(".")[-1]


def _history(session: Session, finding: Finding, invoice: Document) -> list[dict]:
    events = session.scalars(select(AuditEvent).where(or_(
        (AuditEvent.target_type == "finding") & (AuditEvent.target_id == finding.id),
        (AuditEvent.target_type == "document") & (AuditEvent.target_id == invoice.id)
        & AuditEvent.action.in_(["field_corrected", "correction_undone", "document_overrides_changed"]),
    )).order_by(AuditEvent.created_at)).all()
    users = {u.id: u.email for u in session.scalars(select(User).where(User.id.in_({e.user_id for e in events})))}
    out = []
    for e in events:
        d, who = e.details or {}, users.get(e.user_id, "system")
        text = {
            "finding_reviewed": f"{who} set the decision to '{d.get('decision')}'"
                                + (f": {d['note']}" if d.get("note") else ""),
            "finding_evidence_attached": f"{who} attached evidence: {d.get('text', '')}",
            "field_corrected": f"{who} corrected {d.get('field')} from {d.get('before')} to {d.get('after')}: "
                               f"{d.get('reason', '')}",
            "correction_undone": f"{who} undid the correction of {d.get('field')}",
            "document_overrides_changed": f"{who} changed the reading settings to {d.get('after')}",
        }.get(e.action, f"{who}: {e.action}")
        out.append({"at": e.created_at.isoformat(), "text": text})
    return out


def explain(session: Session, finding: Finding) -> dict:
    invoice = session.get(Document, finding.document_id)
    compared = []
    for e in finding.evidence or []:
        line = f"{e.get('document')}: {e.get('field', '').replace('_', ' ')} = {e.get('value')}"
        if e.get("source_line"):
            line += f'  (read from: "{e["source_line"]}")'
        compared.append(line)
    resolve = list(RESOLVE.get(finding.check, ["A document or confirmation from the supplier explaining the difference"]))
    if finding.kind == "possible_reading_error":
        resolve.insert(0, "Compare the value with the original document and correct it if it was misread")
    if finding.check == "matching_order" and invoice and invoice.extraction:
        refs = Extraction.model_validate(invoice.extraction).data.references
        if refs:
            resolve = [f"Upload purchase order {', '.join(refs)}, or link the right order by hand"]
        if "Ambiguous" in finding.explanation:
            resolve = ["Choose which of the candidate orders this invoice belongs to (Matched purchase order panel)"]
    if invoice and invoice.extraction:
        coverage = Extraction.model_validate(invoice.extraction).coverage
        if coverage.missing_fields:
            resolve.append("Missing on the invoice: " + ", ".join(f.replace("_", " ") for f in coverage.missing_fields)
                           + " (correct them if they are on the document)")
    summary = KIND_SUMMARY.get(finding.kind, "") + f" {finding.explanation}"
    if finding.impact is not None and finding.currency and finding.kind == "discrepancy":
        summary += f" Amount at stake: {abs(finding.impact):,.2f} {finding.currency}."
    if finding.review_status == "approved":
        summary += " A reviewer confirmed this issue; that does not approve the invoice for payment."
    return {"finding_id": finding.id, "summary": summary.strip(), "compared": compared,
            "what_would_resolve": resolve if finding.kind != "ok" else [],
            "history": _history(session, finding, invoice) if invoice else [],
            "rule_version": finding.rule_version, "model_versions": finding.model_versions or {}}


def clarification(session: Session, finding: Finding, user: User) -> dict:
    """A draft for the reviewer to edit and send themselves. Veritas never sends it."""
    invoice = session.get(Document, finding.document_id)
    data = Extraction.model_validate(invoice.extraction).data if invoice and invoice.extraction else None
    language = invoice.language if invoice and invoice.language in TEMPLATES else "en"
    t, labels = TEMPLATES[language], FIELD_LABELS[language]
    order = session.get(Document, finding.related_document_id) if finding.related_document_id else None
    number = (data.number if data else None) or (invoice.filename if invoice else "")
    supplier = data.supplier if data else None
    lines = []
    if finding.subject:
        lines.append(f"- {labels['description']}: {finding.subject}")
    for e in finding.evidence or []:
        if e.get("value") not in (None, ""):
            lines.append(f"- {e.get('document')}: {labels.get(_field_name(e.get('field', '')), e.get('field'))} "
                         f"{e.get('value')}")
    if finding.impact is not None and finding.currency and finding.kind == "discrepancy":
        lines.append(f"- {labels['amount']}: {abs(finding.impact):,.2f} {finding.currency}")
    if language == "en":
        lines.append(f"({finding.explanation})")
    body = "\n\n".join([
        t["greeting"].format(supplier=f" {supplier}" if supplier else ""),
        t["intro"].format(invoice=number, order=ORDER_PHRASE[language].format(order=order.number) if order and order.number else ""),
        "\n".join(lines),
        t["ask"],
        t["close"].format(name=user.name),
    ])
    return {"finding_id": finding.id, "language": language, "to": supplier,
            "subject": t["subject"].format(invoice=number), "body": body}


def _transaction(session: Session, doc: Document) -> list[Document]:
    """The document, the orders it is linked to, and the other invoices billed against those orders."""
    ids = {doc.id}
    links = session.scalars(select(Link).where(or_(Link.invoice_id == doc.id, Link.purchase_order_id == doc.id))).all()
    orders = {l.purchase_order_id for l in links} | ({doc.id} if doc.doc_type == "purchase_order" else set())
    ids |= orders | {l.invoice_id for l in links}
    if orders:
        ids |= {l.invoice_id for l in session.scalars(select(Link).where(
            Link.purchase_order_id.in_(orders), Link.status.in_(USABLE_LINKS)))}
    for d in list(session.scalars(select(Document).where(Document.id.in_(ids)))):
        if d.supersedes_id:
            ids.add(d.supersedes_id)
    return list(session.scalars(select(Document).where(Document.id.in_(ids), Document.organization_id == doc.organization_id)))


def timeline(session: Session, doc: Document) -> list[dict]:
    docs = _transaction(session, doc)
    by_id = {d.id: d for d in docs}
    label = {d.id: f"{(d.doc_type or 'document').replace('_', ' ')} {d.number or d.filename}" for d in docs}
    ids = list(by_id)
    users = {u.id: u.email for u in session.scalars(select(User))}
    events: list[tuple[datetime, dict]] = []

    def add(at: datetime | None, kind: str, document_id: int | None, text: str) -> None:
        if at is not None:
            events.append((at, {"at": at.isoformat(), "kind": kind, "document_id": document_id,
                                "label": label.get(document_id), "text": text}))

    for d in docs:
        add(d.created_at, "upload", d.id, f"{label[d.id]} uploaded ({d.filename})"
            + (f", revision {d.revision} replacing an earlier version" if d.supersedes_id else ""))
    for run in session.scalars(select(ProcessingRun).where(ProcessingRun.document_id.in_(ids))):
        if run.status in ("done", "failed"):
            add(run.finished_at, "processing", run.document_id,
                f"{label[run.document_id]} processed" if run.status == "done"
                else f"Processing of {label[run.document_id]} failed: {run.error or ''}"[:300])
    for link in session.scalars(select(Link).where(Link.invoice_id.in_(ids), Link.purchase_order_id.in_(ids))):
        pair = f"{label.get(link.invoice_id)} ↔ {label.get(link.purchase_order_id)}"
        add(link.created_at, "link", link.invoice_id, f"Match {link.status if not link.decided_at else 'proposed'}: {pair}"
            if link.method != "manual" else f"Linked by hand: {pair}")
        if link.decided_at and link.method != "manual":
            add(link.decided_at, "decision", link.invoice_id,
                f"{users.get(link.decided_by_id, 'A reviewer')} {link.status} the match {pair}"
                + (f": {link.note}" if link.note else ""))
    for f in session.scalars(select(Finding).where(Finding.document_id.in_(ids), Finding.kind != "ok")):
        add(f.created_at, "finding", f.document_id, f"Finding ({f.severity}): {f.claim}")
        if f.reviewed_at:
            add(f.reviewed_at, "decision", f.document_id,
                f"Decision '{f.review_status}' on: {f.claim}" + (f" ({f.reviewer_note})" if f.reviewer_note else ""))
    for c in session.scalars(select(Correction).where(Correction.document_id.in_(ids))):
        add(c.created_at, "correction", c.document_id,
            f"{users.get(c.user_id, 'A reviewer')} corrected {c.field_path} on {label[c.document_id]}: "
            f"{c.original_value} → {c.new_value} ({c.reason})" + ("" if c.active else " [later undone]"))
    for a in session.scalars(select(AlertDelivery).where(AlertDelivery.document_id.in_(ids))):
        add(a.created_at, "alert", a.document_id, f"Alert {a.status}: {a.summary or ''}"[:300])
    return [e for _, e in sorted(events, key=lambda pair: pair[0])]


def _key(result) -> tuple[str, str | None]:
    return (result.check, result.subject)


def simulate(session: Session, invoice: Document, changes: list[dict]) -> dict:
    """What would the checks say if these values were different? Nothing is saved.

    changes: [{"document_id", "field_path", "value"}] on the invoice or one of its linked orders.
    """
    from backend.corrections import apply_corrections
    from backend.pipeline import _previously_billed, record_for
    from phase5_verification.engine import verify

    links = session.scalars(select(Link).where(Link.invoice_id == invoice.id, Link.status.in_(USABLE_LINKS))).all()
    orders = [o for o in (session.get(Document, l.purchase_order_id) for l in links) if o is not None and o.extraction]
    allowed = {invoice.id, *(o.id for o in orders)}
    records = {d.id: record_for(session, d) for d in [invoice, *orders]}
    by_doc: dict[int, list[Correction]] = {}
    for change in changes:
        if change["document_id"] not in allowed:
            raise ValueError("Only the invoice and its linked orders can be changed in a simulation")
        value = change["value"]
        try:
            value = str(Decimal(str(value))) if isinstance(value, (int, float)) else value
        except InvalidOperation:
            pass
        # A transient Correction (never added to the session): the same code path as a real correction.
        by_doc.setdefault(change["document_id"], []).append(Correction(field_path=change["field_path"], new_value=value))
    for doc_id, fixes in by_doc.items():
        record = records[doc_id]
        paths = {f.field_path for f in fixes}
        records[doc_id] = record.model_copy(update={
            "data": apply_corrections(record.data, fixes),
            "evidence": {**record.evidence, **{p: "Simulated value" for p in paths}},
            "ungrounded": [u for u in record.ungrounded if u.split("=", 1)[0] not in paths],
        })

    order_records = [records[o.id] for o in orders]
    billed = _previously_billed(session, invoice, orders, {o.id: records[o.id] for o in orders}) if orders else None
    after = {_key(r): r for r in verify(records[invoice.id], order_records, billed) if r.kind != "ok"}
    before = {(f.check, f.subject): f for f in session.scalars(select(Finding).where(
        Finding.document_id == invoice.id, Finding.kind != "ok",
        Finding.review_status.notin_(["superseded"])))}
    if not orders:
        before = {k: v for k, v in before.items() if k[0] != "matching_order"}

    def row(key, b, a) -> dict:
        return {"check": key[0], "subject": key[1], "claim": (a or b).claim,
                "before": b.explanation if b else None, "after": a.explanation if a else None,
                "kind_after": a.kind if a else "ok"}

    return {
        "resolved": [row(k, before[k], None) for k in before if k not in after],
        "remaining": [row(k, before[k], after[k]) for k in before if k in after],
        "new": [row(k, None, after[k]) for k in after if k not in before],
        "note": "Simulation only: no document, finding or decision was changed.",
    }
