import { useState } from "react";
import { errorMessage, reprocessDocument, setOverrides } from "../api.js";
import { LANGUAGE_LABELS, STAGES } from "../format.js";
import { IconRefresh } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import { can, useUser } from "../user.js";
import { isBusy } from "../usePolling.js";

/** Which stage the worker is in, and which page it is reading. */
export function StageProgress({ doc }) {
  if (!isBusy(doc.status)) return null;
  const current = STAGES.findIndex(([key]) => key === doc.stage);
  const { page, pages } = doc.progress ?? {};
  const queued = doc.status === "uploaded";
  return (
    <div className="panel processing" role="status" aria-live="polite">
      <p>{queued ? "Waiting for a worker…" : "Processing in the background. You can leave this page."}</p>
      <ol className="stages">
        {STAGES.map(([key, label], i) => (
          <li key={key} className={!queued && i < current ? "done" : !queued && i === current ? "current" : ""}>
            {label}
            {key === "reading" && i === current && pages ? <span className="small"> · page {page} of {pages}</span> : null}
          </li>
        ))}
      </ol>
      <div className={`progress ${pages && doc.stage === "reading" ? "" : "indeterminate"}`}>
        <span style={pages && doc.stage === "reading" ? { width: `${Math.round((page / pages) * 100)}%` } : undefined} />
      </div>
    </div>
  );
}

/** A failed document: the reason in plain words, and a retry button. */
export function FailureNotice({ doc, onRetry }) {
  const user = useUser();
  if (doc.status !== "failed") return null;
  return (
    <div className="notice notice-critical" role="alert">
      <strong>Processing failed.</strong> {doc.error}
      {can(user, "reviewer") && (
        <button onClick={onRetry} style={{ marginLeft: "0.75rem" }}><IconRefresh size={14} /> Retry</button>
      )}
    </div>
  );
}

const CHOICES = {
  doc_type: [["auto", "Detect"], ["invoice", "Invoice"], ["purchase_order", "Purchase order"], ["contract", "Contract"], ["other", "Other"]],
  language: [["auto", "Detect"], ["en", "English"], ["fr", "French"], ["ar", "Arabic"]],
  currency: [["auto", "Detect"], ["MAD", "MAD"], ["EUR", "EUR"], ["USD", "USD"]],
  day_first: [["auto", "Detect"], ["true", "Day first"], ["false", "Month first"]],
};
const LABELS = { doc_type: "Type", language: "Language", currency: "Currency", day_first: "Dates" };

/** Reading settings (overrides) and the history of processing runs. */
export function ProcessingDetails({ doc, onChanged }) {
  const user = useUser();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const initial = Object.fromEntries(Object.keys(CHOICES).map((k) => {
    const v = doc.overrides?.[k];
    return [k, v === undefined || v === null ? "auto" : String(v)];
  }));
  const [values, setValues] = useState(initial);
  const [busy, setBusy] = useState(false);
  const locale = doc.extraction?.locale;
  const changed = JSON.stringify(values) !== JSON.stringify(initial);

  async function save() {
    setBusy(true);
    try {
      await setOverrides(doc.id, { ...values, day_first: values.day_first === "auto" ? null : values.day_first === "true" });
      toast("Settings saved. The document is being read again.", { tone: "ok" });
      onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-flush">
      <button className="panel-header panel-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h2>Reading settings and processing history</h2>
        <span className="muted small">
          {locale?.language ? LANGUAGE_LABELS[locale.language] ?? locale.language : "Language unknown"}
          {locale?.languages?.length > 1 ? ` (also ${locale.languages.slice(1).map((l) => LANGUAGE_LABELS[l] ?? l).join(", ")})` : ""}
          {" · "}{locale?.currency ?? "currency unknown"}
          {locale?.day_first != null ? ` · ${locale.day_first ? "day" : "month"} first` : ""}
        </span>
      </button>
      <div className={`collapse ${open ? "open" : ""}`}>
        <div>
          <div className="panel-body">
            {locale?.sources && Object.keys(locale.sources).length > 0 && (
              <p className="muted small">
                {Object.entries(locale.sources).map(([k, v]) => `${k.replace("_", " ")}: ${v === "user" ? "set by you" : v}`).join(" · ")}
              </p>
            )}
            {can(user, "reviewer") && (
              <>
                <div className="option-grid">
                  {Object.entries(CHOICES).map(([key, choices]) => (
                    <label key={key}>
                      <span>{LABELS[key]}</span>
                      <select value={values[key]} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                        {choices.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                      </select>
                    </label>
                  ))}
                </div>
                <div className="actions" style={{ marginTop: "0.75rem" }}>
                  <button className="primary" disabled={!changed || busy} onClick={save}>Save and read again</button>
                  <button disabled={busy} onClick={() => reprocessDocument(doc.id, true).then(() => {
                    toast("Reading the file again from scratch.", { tone: "info" });
                    onChanged?.();
                  }, (err) => toast(errorMessage(err), { tone: "critical" }))}>Read file again</button>
                </div>
              </>
            )}
            {doc.runs?.length > 0 && (
              <table className="runs">
                <thead><tr><th>Run</th><th>Status</th><th>Stages</th></tr></thead>
                <tbody>
                  {doc.runs.map((r) => (
                    <tr key={r.id}>
                      <td className="small">{new Date(r.started_at).toLocaleString()}</td>
                      <td className="small">{r.status}{r.error ? `: ${r.error}` : ""}</td>
                      <td className="small">
                        {r.stages.map((s) => s.skipped ? `${s.stage} reused` : `${s.stage} ${s.seconds}s${s.ok ? "" : " ✗"}`).join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
