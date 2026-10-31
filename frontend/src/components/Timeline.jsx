import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, getTimeline } from "../api.js";
import { IconChevron } from "../icons.jsx";

const KIND_LABEL = {
  upload: "Uploaded", processing: "Processed", link: "Match", decision: "Decision",
  finding: "Finding", correction: "Correction", alert: "Alert",
};

/** Orders, invoices, matches, findings, corrections and decisions of this transaction, oldest first. */
export default function Timeline({ docId, version }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    getTimeline(docId).then(setEvents, (err) => setError(errorMessage(err)));
  }, [open, docId, version]);

  return (
    <section className="panel panel-flush">
      <button className="panel-header panel-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h2>Transaction timeline</h2>
        <IconChevron size={14} className={`chevron ${open ? "open" : ""}`} />
      </button>
      <div className={`collapse ${open ? "open" : ""}`}>
        <div>
          {error && <p className="error panel-body">{error}</p>}
          {open && !events && !error && <div className="panel-body"><div className="skeleton" /></div>}
          {events && (
            <ol className="timeline">
              {events.map((e, i) => (
                <li key={i} className={`tl-${e.kind}`}>
                  <time dateTime={e.at}>{new Date(e.at).toLocaleString()}</time>
                  <span className="tl-kind">{KIND_LABEL[e.kind] ?? e.kind}</span>
                  <span dir="auto">
                    {e.document_id && e.document_id !== docId
                      ? <><Link to={`/documents/${e.document_id}`}>{e.label}</Link>: </> : null}
                    {e.text}
                  </span>
                </li>
              ))}
              {events.length === 0 && <li className="muted">Nothing recorded yet.</li>}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
