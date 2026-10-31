import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteDocument, fileUrl, getDocument, previewUrl, reprocessDocument } from "../api.js";
import Badge from "../components/Badge.jsx";
import FindingCard from "../components/FindingCard.jsx";
import { docTypeLabel, money, number } from "../format.js";
import { IconAlert, IconCheck, IconChevron, IconLink, IconRefresh, IconTrash } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import { can, useUser } from "../user.js";
import usePolling, { isBusy } from "../usePolling.js";

const IMAGE = /\.(png|jpe?g|tiff?|bmp|webp)$/i;
const busy = (doc) => isBusy(doc.status);
const FIELDS = [
  ["number", "Number"], ["references", "References"], ["issue_date", "Issued"],
  ["due_date", "Payment due"], ["delivery_date", "Delivery / shipped"], ["buyer", "Buyer"],
  ["supplier", "Supplier"], ["currency", "Currency"], ["subtotal", "Subtotal", true],
  ["tax", "Tax", true], ["total", "Total", true], ["payment_terms", "Payment terms"],
];

// Does this finding talk about this line item? (Claims quote the item description.)
const mentions = (finding, description) => !!finding && finding.claim.includes(description);

function Lightbox({ src, alt, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay lightbox" onClick={onClose} role="dialog" aria-label={alt}>
      <img src={src} alt={alt} />
      <span className="lightbox-hint">Click anywhere or press Esc to close</span>
    </div>
  );
}

function Viewer({ doc }) {
  const [zoomed, setZoomed] = useState(null);
  const pages = doc.pages?.length ? doc.pages : [{ number: 1 }];
  // PDFs and images are shown as server-rendered page images (works in every browser);
  // Word and text files are shown as their extracted text.
  const visual = IMAGE.test(doc.filename) || /\.pdf$/i.test(doc.filename);
  return (
    <section className="panel panel-flush viewer-panel rise" style={{ "--i": 1 }}>
      <div className="panel-header">
        <h2>Original document</h2>
        <a href={fileUrl(doc.id)} target="_blank" rel="noreferrer" className="small">Open file</a>
      </div>
      {visual
        ? pages.map((p) => (
            <button key={p.number} className="page-thumb" onClick={() => setZoomed(previewUrl(doc.id, p.number))}
                    title="Click to zoom">
              <img className="viewer" src={previewUrl(doc.id, p.number)} alt={`${doc.filename}, page ${p.number}`} />
            </button>
          ))
        : <pre className="viewer viewer-text">{doc.text}</pre>}
      {doc.pages?.length > 0 && (
        <div className="viewer-footer">
          {doc.pages.map((p) => `Page ${p.number}: ${p.method === "ocr" ? "read by OCR" : `read as ${p.method}`}` +
            (p.confidence != null ? ` (confidence ${(p.confidence * 100).toFixed(1)}%)` : "")).join(" · ")}
        </div>
      )}
      {zoomed && <Lightbox src={zoomed} alt={doc.filename} onClose={() => setZoomed(null)} />}
    </section>
  );
}

function Verdict({ problems, passed }) {
  const critical = problems.filter((f) => f.severity === "critical" && f.review_status === "pending").length;
  const open = problems.filter((f) => f.review_status === "pending").length;
  if (critical)
    return (
      <div className="verdict verdict-critical"><IconAlert size={26} />
        <div>{critical} critical issue{critical > 1 ? "s" : ""} need{critical > 1 ? "" : "s"} review
          <small>{passed} other checks passed</small></div>
      </div>
    );
  if (open)
    return (
      <div className="verdict verdict-warning"><IconAlert size={26} />
        <div>{open} point{open > 1 ? "s" : ""} to review<small>{passed} checks passed</small></div>
      </div>
    );
  return (
    <div className="verdict verdict-ok"><IconCheck size={26} />
      <div>All checks passed or reviewed<small>{passed} checks passed</small></div>
    </div>
  );
}

function ComparisonTable({ comparison, currency, focus, onFocus }) {
  const changed = (a, b) => a != null && b != null && Number(a) !== Number(b);
  return (
    <section className="panel panel-flush rise" style={{ "--i": 2 }}>
      <div className="panel-header">
        <h2>Order vs invoice</h2>
        <Link to={`/documents/${comparison.purchase_order_id}`} className="small">
          {comparison.purchase_order_number ?? "Purchase order"}
        </Link>
      </div>
      <table>
        <thead>
          <tr>
            <th>Item</th><th className="num">Ordered</th><th className="num">Invoiced</th>
            <th className="num">Unit price</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((r) => (
            <tr key={r.description}
                className={`row-${r.status} ${focus === r.description ? "linked" : ""}`}
                onMouseEnter={() => onFocus(r.description)} onMouseLeave={() => onFocus(null)}>
              <td>{r.description}</td>
              <td className="num">{number(r.ordered_quantity)}</td>
              <td className={`num ${changed(r.ordered_quantity, r.invoiced_quantity) ? "diff" : ""}`}>
                {number(r.invoiced_quantity)}
              </td>
              <td className={`num ${changed(r.ordered_price, r.invoiced_price) ? "diff" : ""}`}>
                {money(r.invoiced_price ?? r.ordered_price, currency)}
                {changed(r.ordered_price, r.invoiced_price) && (
                  <div className="muted small">ordered at {money(r.ordered_price, currency)}</div>
                )}
              </td>
              <td><Badge value={r.status} /></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Total incl. tax</td>
            <td className="num">{money(comparison.ordered_total, currency)}</td>
            <td className={`num ${changed(comparison.ordered_total, comparison.invoiced_total) ? "diff" : ""}`}>
              {money(comparison.invoiced_total, currency)}
            </td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </section>
  );
}

function ExtractedData({ extraction }) {
  const [open, setOpen] = useState(null);
  const { data, evidence, ungrounded, filled_by_rules: filled, method } = extraction;
  const show = (value, isMoney) =>
    Array.isArray(value) ? value.join(", ") : isMoney ? money(value, data.currency ?? "USD") : value;
  return (
    <section className="panel panel-flush rise" style={{ "--i": 3 }}>
      <div className="panel-header">
        <h2>Extracted data</h2>
        <span className="muted small">{method === "llm" ? "Local LLM + rules" : "Rules"} · click a value to see where it came from</span>
      </div>
      {ungrounded.length > 0 && (
        <p className="error" style={{ padding: "0 1.1rem" }}>Not found in the document (possible AI error): {ungrounded.join(", ")}</p>
      )}
      <div className="fields">
        {FIELDS.filter(([key]) => data[key] != null && data[key].length !== 0).map(([key, label, isMoney]) => (
          <div key={key} className={`field ${open === key ? "open" : ""}`}>
            <button className="field-row" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
              <span className="field-label">{label}</span>
              <span className="field-value">
                {show(data[key], isMoney)}
                {filled.includes(key) && <span className="source-hint"> · filled by rules</span>}
              </span>
              <IconChevron size={14} className="chevron" />
            </button>
            <div className="collapse">
              <div>
                <div className="field-source">
                  {evidence[key]
                    ? <><span>Source line</span><code>{evidence[key]}</code></>
                    : <span>No single source line (a label or code assigned by the extractor)</span>}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function DocumentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const user = useUser();
  const [showPassed, setShowPassed] = useState(false);
  const [focus, setFocus] = useState(null); // line item highlighted in both findings and table
  const loader = useCallback(() => getDocument(id), [id]);
  const { data: doc, error, reload } = usePolling(loader, busy);

  if (error) return <p className="error">Document not found.</p>;
  if (!doc) return <div className="skeleton" style={{ height: 300 }} />;

  const data = doc.extraction?.data;
  const problems = doc.findings.filter((f) => f.verdict !== "supported");
  const passed = doc.findings.filter((f) => f.verdict === "supported");
  const currency = data?.currency ?? "USD";
  const rowFor = (finding) => doc.comparison?.rows.find((r) => mentions(finding, r.description))?.description ?? null;

  return (
    <>
      <header className="page-header">
        <div>
          <div className="doc-title">
            <h1>{data?.number ?? doc.filename}</h1>
            <Badge value={doc.doc_type} />
            <Badge value={doc.status} />
          </div>
          <p>{doc.filename}</p>
        </div>
        <div className="actions">
          {can(user, "reviewer") && (
            <button className="ghost" onClick={() => reprocessDocument(doc.id).then(() => {
              toast("Reprocessing started", { tone: "info" });
              reload();
            })}><IconRefresh size={16} /> Reprocess</button>
          )}
          {can(user, "admin") && (
            <button className="ghost" onClick={() => {
              if (confirm(`Delete ${doc.filename}?`))
                deleteDocument(doc.id).then(() => {
                  toast(`${doc.filename} deleted`, { tone: "ok" });
                  navigate("/documents");
                });
            }}><IconTrash size={16} /> Delete</button>
          )}
        </div>
      </header>

      {doc.error && <p className="error">{doc.error}</p>}
      {isBusy(doc.status) && (
        <div className="panel processing">
          <p>Processing in the background: reading, extracting, matching and verifying…</p>
          <div className="progress indeterminate"><span /></div>
        </div>
      )}

      {data && (
        <section className="panel rise" style={{ marginBottom: "1.5rem" }}>
          <div className="summary">
            <div><span>Type</span><strong>{docTypeLabel(data.doc_type)}</strong></div>
            <div><span>Supplier</span><strong>{data.supplier ?? "—"}</strong></div>
            <div><span>Buyer</span><strong>{data.buyer ?? "—"}</strong></div>
            <div><span>Issued</span><strong>{data.issue_date ?? "—"}</strong></div>
            <div><span>Total</span><strong>{money(data.total, currency)}</strong></div>
          </div>
          {doc.links.map((l) => (
            <div key={l.document_id} className="related" style={{ margin: "1rem -1.25rem -1.25rem" }}>
              <IconLink size={16} />
              <span>Linked to {docTypeLabel(l.relation).toLowerCase()}{" "}
                <Link to={`/documents/${l.document_id}`}>{l.number ?? l.filename}</Link></span>
              <span className="muted small">({l.reasons.join(", ")})</span>
            </div>
          ))}
        </section>
      )}

      <div className="columns">
        <div className="stack">
          {doc.doc_type === "invoice" && doc.findings.length > 0 && (
            <section>
              <Verdict problems={problems} passed={passed.length} />
              <div style={{ marginTop: "1rem" }}>
                {problems.map((f, i) => (
                  <FindingCard key={f.id} finding={f} onChanged={reload} style={{ "--i": i }}
                               highlighted={focus !== null && mentions(f, focus)}
                               onHover={(hovered) => setFocus(hovered ? rowFor(hovered) : null)} />
                ))}
              </div>
              {passed.length > 0 && (
                <button className="link toggle" style={{ marginTop: "0.75rem" }} onClick={() => setShowPassed(!showPassed)}
                        aria-expanded={showPassed}>
                  <IconChevron size={14} className={`chevron ${showPassed ? "open" : ""}`} />
                  {showPassed ? "Hide" : "Show"} the {passed.length} checks that passed
                </button>
              )}
              <div className={`collapse ${showPassed ? "open" : ""}`}>
                <div>
                  <div style={{ paddingTop: "0.75rem" }}>
                    {passed.map((f) => (
                      <FindingCard key={f.id} finding={f} highlighted={focus !== null && mentions(f, focus)}
                                   onHover={(hovered) => setFocus(hovered ? rowFor(hovered) : null)} />
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}
          {doc.comparison && (
            <ComparisonTable comparison={doc.comparison} currency={currency} focus={focus} onFocus={setFocus} />
          )}
          {doc.extraction && <ExtractedData extraction={doc.extraction} />}
        </div>
        <Viewer doc={doc} />
      </div>
    </>
  );
}
