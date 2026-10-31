import { useState } from "react";
import { errorMessage, simulateCorrections } from "../api.js";
import { IconChevron } from "../icons.jsx";

/**
 * "What if": try a different value (e.g. the quantity on the delivery note) and see which
 * findings would disappear, remain or appear. Nothing is saved.
 */
export default function Simulator({ doc }) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(String(doc.id));
  const [path, setPath] = useState("");
  const [value, setValue] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const data = doc.effective ?? doc.extraction?.data;
  const orders = doc.links.filter((l) => l.relation === "purchase_order" && ["proposed", "confirmed"].includes(l.status));
  const fields = [
    ["total", "Total"], ["subtotal", "Subtotal"], ["tax", "Tax"], ["currency", "Currency"],
    ...(data?.line_items ?? []).flatMap((item, i) => [
      [`line_items.${i}.quantity`, `${item.description}: quantity`],
      [`line_items.${i}.unit_price`, `${item.description}: unit price`],
    ]),
  ];

  async function run(e) {
    e.preventDefault();
    if (!path) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await simulateCorrections(doc.id, [{ document_id: Number(target), field_path: path, value: value === "" ? null : value }]));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel panel-flush">
      <button className="panel-header panel-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h2>Simulate a correction</h2>
        <span className="muted small">See what would change; nothing is saved <IconChevron size={14} className={`chevron ${open ? "open" : ""}`} /></span>
      </button>
      <div className={`collapse ${open ? "open" : ""}`}>
        <div>
          <form className="panel-body simulate" onSubmit={run}>
            <select value={target} onChange={(e) => { setTarget(e.target.value); setPath(""); }} aria-label="Document">
              <option value={doc.id}>This invoice</option>
              {orders.map((o) => <option key={o.document_id} value={o.document_id}>Order {o.number ?? o.filename}</option>)}
            </select>
            {String(doc.id) === target ? (
              <select value={path} onChange={(e) => setPath(e.target.value)} aria-label="Field">
                <option value="">Choose a value…</option>
                {fields.map(([p, label]) => <option key={p} value={p}>{label}</option>)}
              </select>
            ) : (
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="Field, e.g. line_items.0.quantity"
                     aria-label="Field path" />
            )}
            <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Hypothetical value" aria-label="Value" />
            <button type="submit" disabled={busy || !path}>Simulate</button>
          </form>
          {error && <p className="error panel-body">{error}</p>}
          {result && (
            <div className="panel-body sim-result">
              <p className="muted small">{result.note}</p>
              {[["resolved", "Would be resolved"], ["remaining", "Would remain"], ["new", "Would appear"]].map(([key, label]) => (
                result[key].length > 0 && (
                  <div key={key} className={`sim-${key}`}>
                    <strong>{label} ({result[key].length})</strong>
                    <ul>
                      {result[key].map((r, i) => (
                        <li key={i}>{r.claim}{r.after && <span className="muted small"> · {r.after}</span>}</li>
                      ))}
                    </ul>
                  </div>
                )
              ))}
              {!result.resolved.length && !result.new.length && <p>No finding would change.</p>}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
