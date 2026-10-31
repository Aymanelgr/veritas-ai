import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { confirmLink, createLink, errorMessage, listDocuments, rejectLink } from "../api.js";
import { docTypeLabel } from "../format.js";
import { IconLink } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import { can, useUser } from "../user.js";
import Badge from "./Badge.jsx";

const STATUS = {
  proposed: ["Proposed automatically", "warning"],
  ambiguous: ["Ambiguous match — review required", "critical"],
  conflict: ["Not linked: details differ", "critical"],
  confirmed: ["Confirmed by a reviewer", "supported"],
  rejected: ["Unlinked by a reviewer", "rejected"],
};
const STRENGTH = { strong: "Strong evidence", medium: "Some evidence", weak: "Weak evidence" };

function LinkRow({ link, onChanged }) {
  const user = useUser();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [label, tone] = STATUS[link.status] ?? [link.status, "warning"];
  const decidable = can(user, "reviewer") && link.relation === "purchase_order";

  async function act(action) {
    if (action === "reject" && !note.trim()) {
      toast("Say why these documents do not belong together.", { tone: "critical" });
      return;
    }
    setBusy(true);
    try {
      await (action === "confirm" ? confirmLink(link.id, note) : rejectLink(link.id, note));
      toast(action === "confirm" ? "Match confirmed. Checks are running again." : "Unlinked. Checks are running again.",
            { tone: "ok" });
      setNote("");
      onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`link-row link-${link.status}`}>
      <div className="link-head">
        <IconLink size={16} />
        <span>{docTypeLabel(link.relation)}{" "}
          <Link to={`/documents/${link.document_id}`}>{link.number ?? link.filename}</Link></span>
        <Badge value={tone} label={label} />
        {link.method !== "manual" && <span className="muted small">{STRENGTH[link.strength]}</span>}
      </div>
      {link.reasons.length > 0 && (
        <ul className="reasons">
          {link.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {link.note && <p className="muted small">Reviewer note: “{link.note}”</p>}
      {decidable && link.status !== "rejected" && (
        <div className="review">
          <input placeholder={link.status === "confirmed" ? "Reason for unlinking" : "Note (required to unlink)"}
                 value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note for this decision" />
          {link.status !== "confirmed" && (
            <button className="primary" disabled={busy} onClick={() => act("confirm")}>Confirm match</button>
          )}
          <button disabled={busy} onClick={() => act("reject")}>Unlink</button>
        </div>
      )}
    </li>
  );
}

// Link this invoice to the right order by hand, with a reason (recorded in the audit history).
function ManualLink({ invoice, linkedIds, onChanged }) {
  const toast = useToast();
  const [orders, setOrders] = useState(null);
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listDocuments().then((docs) => setOrders(docs.filter((d) => d.doc_type === "purchase_order" && d.is_current
      && !d.duplicate_of_id && !linkedIds.includes(d.id))), () => setOrders([]));
  }, [linkedIds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e) {
    e.preventDefault();
    if (!choice || !note.trim()) return;
    setBusy(true);
    try {
      await createLink(invoice.id, Number(choice), note.trim());
      toast("Linked. Checks are running again.", { tone: "ok" });
      setChoice("");
      setNote("");
      onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
    }
  }

  if (orders === null) return null;
  if (!orders.length) return <p className="muted small">No other purchase order is available to link.</p>;
  return (
    <form className="review manual-link" onSubmit={submit}>
      <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Purchase order">
        <option value="">Link to another purchase order…</option>
        {orders.map((o) => <option key={o.id} value={o.id}>{o.number ?? o.filename}</option>)}
      </select>
      <input placeholder="Why these belong together (required)" value={note} onChange={(e) => setNote(e.target.value)}
             aria-label="Reason for linking" />
      <button type="submit" disabled={busy || !choice || !note.trim()}>Link</button>
    </form>
  );
}

export default function LinksPanel({ doc, onChanged }) {
  const user = useUser();
  const isInvoice = doc.doc_type === "invoice";
  if (!isInvoice && !doc.links.length) return null;
  const linkedIds = doc.links.filter((l) => l.status !== "rejected").map((l) => l.document_id);
  return (
    <section className="panel panel-flush rise">
      <div className="panel-header">
        <h2>{isInvoice ? "Matched purchase order" : "Invoices billed against this order"}</h2>
        <span className="muted small">A matching reference alone is not trusted: supplier and buyer are checked too</span>
      </div>
      {doc.links.length ? (
        <ul className="links">{doc.links.map((l) => <LinkRow key={l.id} link={l} onChanged={onChanged} />)}</ul>
      ) : (
        <p className="empty small">No purchase order has been matched to this invoice yet.</p>
      )}
      {isInvoice && can(user, "reviewer") && (
        <div className="panel-footer"><ManualLink invoice={doc} linkedIds={linkedIds} onChanged={onChanged} /></div>
      )}
    </section>
  );
}
