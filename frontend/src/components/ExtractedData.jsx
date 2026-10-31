import { useState } from "react";
import { addCorrection, errorMessage, undoCorrection } from "../api.js";
import { date, money, number } from "../format.js";
import { IconChevron } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import { can, useUser } from "../user.js";

// [field path, label, kind]; kind decides formatting and the editor's input type.
const FIELDS = [
  ["number", "Number"], ["references", "References", "list"], ["issue_date", "Issued", "date"],
  ["due_date", "Payment due", "date"], ["delivery_date", "Delivery / shipped", "date"], ["buyer", "Buyer"],
  ["supplier", "Supplier"], ["currency", "Currency", "currency"], ["subtotal", "Subtotal", "money"],
  ["tax", "Tax", "money"], ["total", "Total", "money"], ["payment_terms", "Payment terms"],
];
const ITEM_COLUMNS = [["description", "Item"], ["code", "Code"], ["quantity", "Qty", "number"],
  ["unit", "Unit"], ["unit_price", "Unit price", "money"], ["total", "Line total", "money"]];
const PAGE_SIZE = 25;

function useCorrect(docId, onChanged) {
  const toast = useToast();
  return async (path, value, reason) => {
    try {
      await addCorrection(docId, path, value === "" ? null : value, reason);
      toast("Corrected. The original value is kept and the checks are running again.", { tone: "ok" });
      onChanged?.();
      return true;
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
      return false;
    }
  };
}

// Inline editor: new value + required reason.
function Editor({ initial, kind, onSave, onCancel }) {
  const [value, setValue] = useState(initial ?? "");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form className="editor" onSubmit={async (e) => {
      e.preventDefault();
      if (!reason.trim()) return;
      setBusy(true);
      const ok = await onSave(kind === "list" ? value.split(",").map((s) => s.trim()).filter(Boolean) : value, reason.trim());
      setBusy(false);
      if (ok) onCancel();
    }}>
      {kind === "currency" ? (
        <select value={value} onChange={(e) => setValue(e.target.value)} aria-label="New value">
          <option value="">Unknown</option><option>MAD</option><option>EUR</option><option>USD</option>
        </select>
      ) : (
        <input autoFocus type={kind === "date" ? "date" : "text"} value={Array.isArray(value) ? value.join(", ") : value}
               inputMode={kind === "money" || kind === "number" ? "decimal" : undefined}
               placeholder={kind === "money" || kind === "number" ? "e.g. 1234.56" : ""}
               onChange={(e) => setValue(e.target.value)} aria-label="New value" />
      )}
      <input placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
      <button type="submit" className="primary" disabled={busy || !reason.trim()}>Save</button>
      <button type="button" className="ghost" onClick={onCancel}>Cancel</button>
    </form>
  );
}

function Coverage({ extraction }) {
  const c = extraction.coverage ?? {};
  const issues = [
    ...(extraction.ungrounded ?? []).map((f) => `Not found in the document (possible AI error): ${f}`),
    ...(extraction.ambiguities ?? []),
    ...(extraction.locale?.problems ?? []),
    ...(extraction.warnings ?? []),
    ...(c.missing_fields?.length ? [`Not found: ${c.missing_fields.join(", ").replaceAll("_", " ")}`] : []),
  ];
  const skipped = c.skipped_lines ?? [];
  return (
    <div className="coverage">
      <span>{c.pages ?? 0} page{c.pages === 1 ? "" : "s"} read</span>
      <span>{c.line_items_extracted ?? 0} line item{c.line_items_extracted === 1 ? "" : "s"} extracted
        {c.table_rows_found ? ` of ${c.table_rows_found} table rows found` : ""}</span>
      {(c.ignored_lines?.length ?? 0) > 0 && <span>{c.ignored_lines.length} repeated header/subtotal lines ignored</span>}
      {skipped.length > 0 && (
        <details>
          <summary className="error">{skipped.length} table line{skipped.length > 1 ? "s" : ""} could not be read</summary>
          <pre dir="auto">{skipped.join("\n")}</pre>
        </details>
      )}
      {issues.length > 0 && <ul className="issues">{issues.map((t, i) => <li key={i}>{t}</li>)}</ul>}
    </div>
  );
}

export default function ExtractedData({ doc, onChanged }) {
  const user = useUser();
  const toast = useToast();
  const correct = useCorrect(doc.id, onChanged);
  const [open, setOpen] = useState(null);
  const [editing, setEditing] = useState(null); // field path being edited
  const [page, setPage] = useState(0);
  const { extraction } = doc;
  const data = doc.effective ?? extraction.data;
  const lang = doc.language;
  const editable = can(user, "reviewer");
  const corrected = new Map(doc.corrections.filter((c) => c.active).map((c) => [c.field_path, c]));
  const raw = extraction.raw_values ?? {};

  const show = (value, kind) => {
    if (value == null || value === "" || (Array.isArray(value) && !value.length)) return <span className="muted">—</span>;
    if (kind === "list") return value.join(", ");
    if (kind === "money") return money(value, data.currency, lang);
    if (kind === "number") return number(value, lang);
    if (kind === "date") return date(value, lang);
    return <bdi>{value}</bdi>;
  };

  const items = data.line_items ?? [];
  const pages = Math.ceil(items.length / PAGE_SIZE);
  const shownItems = items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <section className="panel panel-flush rise" style={{ "--i": 3 }}>
      <div className="panel-header">
        <h2>Extracted data</h2>
        <span className="muted small">{extraction.method === "llm" ? "Local LLM + rules" : "Rules"} · click a value to see where it came from</span>
      </div>
      <Coverage extraction={extraction} />
      {!data.currency && (
        <p className="notice">The currency could not be determined, so amounts are not compared with other documents.
          {editable && " Set it below if you know it."}</p>
      )}
      <div className="fields">
        {FIELDS.map(([key, label, kind]) => {
          const fix = corrected.get(key);
          return (
            <div key={key} className={`field ${open === key ? "open" : ""}`}>
              <button className="field-row" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
                <span className="field-label">{label}</span>
                <span className="field-value">
                  {show(data[key], kind)}
                  {fix && <span className="source-hint corrected"> · corrected</span>}
                  {!fix && extraction.filled_by_rules?.includes(key) && <span className="source-hint"> · filled by rules</span>}
                </span>
                <IconChevron size={14} className="chevron" />
              </button>
              <div className="collapse">
                <div>
                  <div className="field-source">
                    {extraction.evidence?.[key]
                      ? <><span>Source line</span><code dir="auto">{extraction.evidence[key]}</code></>
                      : <span>No single source line (a label or code assigned by the extractor)</span>}
                    {raw[key] && <div className="small">Written as “{raw[key]}”</div>}
                    {fix && <div className="small">Originally {JSON.stringify(fix.original_value)} · corrected: “{fix.reason}”</div>}
                  </div>
                  {editable && (editing === key
                    ? <Editor initial={data[key]} kind={kind} onCancel={() => setEditing(null)}
                              onSave={(value, reason) => correct(key, value, reason)} />
                    : <button className="link edit-link" onClick={() => setEditing(key)}>Correct this value</button>)}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {items.length > 0 && (
        <>
          <h3 className="subhead">Line items ({items.length})</h3>
          <div className="table-scroll">
            <table className="items">
              <thead><tr>{ITEM_COLUMNS.map(([, label, kind]) => <th key={label} className={kind ? "num" : ""}>{label}</th>)}</tr></thead>
              <tbody>
                {shownItems.map((item, offset) => {
                  const index = page * PAGE_SIZE + offset;
                  return (
                    <tr key={index}>
                      {ITEM_COLUMNS.map(([col, , kind]) => {
                        const path = `line_items.${index}.${col}`;
                        const fix = corrected.get(path);
                        return (
                          <td key={col} className={`${kind ? "num" : ""} ${fix ? "corrected" : ""}`}
                              title={fix ? `Originally ${JSON.stringify(fix.original_value)}: ${fix.reason}` : extraction.evidence?.[path]}>
                            {editing === path ? (
                              <Editor initial={item[col]} kind={kind} onCancel={() => setEditing(null)}
                                      onSave={(value, reason) => correct(path, value, reason)} />
                            ) : editable ? (
                              <button className="cell-edit" onClick={() => setEditing(path)} aria-label={`Correct ${col} of row ${index + 1}`}>
                                {show(item[col], kind)}
                              </button>
                            ) : show(item[col], kind)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div className="pager">
              <button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
              <span className="muted small">Rows {page * PAGE_SIZE + 1}–{Math.min(items.length, (page + 1) * PAGE_SIZE)} of {items.length}</span>
              <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}

      {doc.corrections.length > 0 && (
        <>
          <h3 className="subhead">Correction history</h3>
          <ul className="history">
            {doc.corrections.map((c) => (
              <li key={c.id} className={c.active ? "" : "muted"}>
                <code>{c.field_path}</code>: {JSON.stringify(c.original_value)} → {JSON.stringify(c.new_value)}
                <span className="muted small"> · “{c.reason}” · {new Date(c.created_at).toLocaleString()}</span>
                {!c.active && <span className="small"> · undone</span>}
                {c.active && editable && (
                  <button className="link small" onClick={() => undoCorrection(doc.id, c.id).then(() => {
                    toast("Correction undone. The checks are running again.", { tone: "ok" });
                    onChanged?.();
                  }, (err) => toast(errorMessage(err), { tone: "critical" }))}>Undo</button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
