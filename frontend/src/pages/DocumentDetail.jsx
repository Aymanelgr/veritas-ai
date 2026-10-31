import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { deleteDocument, errorMessage, fileUrl, getDocument, previewUrl, reprocessDocument } from "../api.js";
import Badge from "../components/Badge.jsx";
import ExtractedData from "../components/ExtractedData.jsx";
import FindingCard from "../components/FindingCard.jsx";
import LinksPanel from "../components/LinksPanel.jsx";
import { FailureNotice, ProcessingDetails, StageProgress } from "../components/Processing.jsx";
import Simulator from "../components/Simulator.jsx";
import Timeline from "../components/Timeline.jsx";
import { date, docTypeLabel, money, number } from "../format.js";
import { IconAlert, IconCheck, IconChevron, IconQuestion, IconRefresh, IconTrash } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import { can, useUser } from "../user.js";
import usePolling, { isBusy } from "../usePolling.js";

const IMAGE = /\.(png|jpe?g|tiff?|bmp|webp)$/i;
const busy = (doc) => isBusy(doc.status);

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
        : <pre className="viewer viewer-text" dir={doc.language === "ar" ? "rtl" : "auto"}>{doc.text}</pre>}
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

// "All checks passed" is only said when every check ran; a check that could not run is never a pass.
function Verdict({ problems, passed }) {
  const open = problems.filter((f) => f.review_status === "pending");
  const critical = open.filter((f) => f.severity === "critical").length;
  const unchecked = problems.filter((f) => f.kind === "not_checked" && !["resolved", "rejected"].includes(f.review_status)).length;
  const extra = unchecked ? ` · ${unchecked} check${unchecked > 1 ? "s" : ""} could not run` : "";
  if (critical)
    return (
      <div className="verdict verdict-critical"><IconAlert size={26} />
        <div>{critical} critical issue{critical > 1 ? "s" : ""} need{critical > 1 ? "" : "s"} review
          <small>{passed} checks passed{extra}</small></div>
      </div>
    );
  if (open.length)
    return (
      <div className="verdict verdict-warning"><IconAlert size={26} />
        <div>{open.length} point{open.length > 1 ? "s" : ""} to review<small>{passed} checks passed{extra}</small></div>
      </div>
    );
  if (unchecked)
    return (
      <div className="verdict verdict-warning"><IconQuestion size={26} />
        <div>Reviewed, but {unchecked} check{unchecked > 1 ? "s" : ""} could not run
          <small>{passed} checks passed. Missing information limits what was verified.</small></div>
      </div>
    );
  return (
    <div className="verdict verdict-ok"><IconCheck size={26} />
      <div>All checks ran; each passed or was reviewed<small>{passed} checks passed · reviewing a finding is not payment approval</small></div>
    </div>
  );
}

const ROWS_PER_PAGE = 25;

function ComparisonTable({ comparison, language, focus, onFocus }) {
  const [page, setPage] = useState(0);
  const changed = (a, b) => a != null && b != null && Number(a) !== Number(b);
  const currency = comparison.currency;
  // Prices are only shown side by side as money when both documents use the same, known currency.
  const price = (v) => (comparison.money_comparable ? money(v, currency, language) : number(v, language));
  const pages = Math.ceil(comparison.rows.length / ROWS_PER_PAGE);
  const rows = comparison.rows.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE);
  return (
    <section className="panel panel-flush rise" style={{ "--i": 2 }}>
      <div className="panel-header">
        <h2>Order vs invoice</h2>
        <Link to={`/documents/${comparison.purchase_order_id}`} className="small">
          {comparison.purchase_order_number ?? "Purchase order"}
        </Link>
      </div>
      {!comparison.money_comparable && (
        <p className="notice">The currencies differ or are unknown, so prices and totals are not compared. Quantities still are.</p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Item</th><th className="num">Ordered</th><th className="num">Invoiced</th>
              <th className="num">Unit price</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.description}-${i}`}
                  className={`row-${r.status} ${focus === r.description ? "linked" : ""}`}
                  onMouseEnter={() => onFocus(r.description)} onMouseLeave={() => onFocus(null)}>
                <td dir="auto">{r.description}</td>
                <td className="num">{number(r.ordered_quantity, language)}</td>
                <td className={`num ${changed(r.ordered_quantity, r.invoiced_quantity) ? "diff" : ""}`}>
                  {number(r.invoiced_quantity, language)}
                  {changed(r.ordered_quantity, r.invoiced_quantity) && (
                    <div className="muted small">
                      {Number(r.invoiced_quantity) > Number(r.ordered_quantity) ? "+" : ""}
                      {number(Number(r.invoiced_quantity) - Number(r.ordered_quantity), language)}
                    </div>
                  )}
                </td>
                <td className={`num ${comparison.money_comparable && changed(r.ordered_price, r.invoiced_price) ? "diff" : ""}`}>
                  {price(r.invoiced_price ?? r.ordered_price)}
                  {changed(r.ordered_price, r.invoiced_price) && (
                    <div className="muted small">ordered at {price(r.ordered_price)}</div>
                  )}
                </td>
                <td><Badge value={r.status} /></td>
              </tr>
            ))}
          </tbody>
          {comparison.money_comparable && (
            <tfoot>
              <tr>
                <td>Total incl. tax</td>
                <td className="num">{money(comparison.ordered_total, currency, language)}</td>
                <td className={`num ${changed(comparison.ordered_total, comparison.invoiced_total) ? "diff" : ""}`}>
                  {money(comparison.invoiced_total, currency, language)}
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="muted small">Page {page + 1} of {pages}</span>
          <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
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

  const data = doc.effective ?? doc.extraction?.data;
  const lang = doc.language;
  const problems = doc.findings.filter((f) => f.verdict !== "supported");
  const passed = doc.findings.filter((f) => f.verdict === "supported");
  const rowFor = (finding) => doc.comparison?.rows.find((r) => mentions(finding, r.description))?.description ?? null;
  const retry = () => reprocessDocument(doc.id).then(() => {
    toast("Processing started again", { tone: "info" });
    reload();
  }, (err) => toast(errorMessage(err), { tone: "critical" }));

  return (
    <>
      <header className="page-header">
        <div>
          <div className="doc-title">
            <h1 dir="auto">{data?.number ?? doc.filename}</h1>
            <Badge value={doc.doc_type} />
            <Badge value={doc.status} />
            {doc.revision > 1 && <Badge value="info" label={`Revision ${doc.revision}`} />}
          </div>
          <p>{doc.filename}</p>
        </div>
        <div className="actions">
          {can(user, "reviewer") && (
            <button className="ghost" onClick={retry}><IconRefresh size={16} /> Reprocess</button>
          )}
          {can(user, "admin") && (
            <button className="ghost" onClick={() => {
              if (confirm(`Delete ${doc.filename}?`))
                deleteDocument(doc.id).then(() => {
                  toast(`${doc.filename} deleted`, { tone: "ok" });
                  navigate("/documents");
                }, (err) => toast(errorMessage(err), { tone: "critical" }));
            }}><IconTrash size={16} /> Delete</button>
          )}
        </div>
      </header>

      <FailureNotice doc={doc} onRetry={retry} />
      {doc.duplicate_of_id && (
        <p className="notice">This file was already uploaded, so it is not processed again. See{" "}
          <Link to={`/documents/${doc.duplicate_of_id}`}>the original upload</Link>.</p>
      )}
      {!doc.is_current && !doc.duplicate_of_id && (
        <p className="notice">A newer revision of this document exists. Checks use the newest revision only.</p>
      )}
      {doc.supersedes_id && (
        <p className="notice">This is revision {doc.revision}. It replaces{" "}
          <Link to={`/documents/${doc.supersedes_id}`}>the previous version</Link>.</p>
      )}
      <StageProgress doc={doc} />

      {data && (
        <section className="panel rise" style={{ marginBottom: "1.5rem" }}>
          <div className="summary">
            <div><span>Type</span><strong>{docTypeLabel(data.doc_type)}</strong></div>
            <div><span>Supplier</span><strong dir="auto">{data.supplier ?? "—"}</strong></div>
            <div><span>Buyer</span><strong dir="auto">{data.buyer ?? "—"}</strong></div>
            <div><span>Issued</span><strong>{date(data.issue_date, lang)}</strong></div>
            <div><span>Total</span><strong>{money(data.total, data.currency, lang)}</strong></div>
          </div>
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
          {doc.extraction && <LinksPanel doc={doc} onChanged={reload} />}
          {doc.comparison && (
            <ComparisonTable comparison={doc.comparison} language={lang} focus={focus} onFocus={setFocus} />
          )}
          {doc.extraction && <ExtractedData doc={doc} onChanged={reload} />}
          {doc.doc_type === "invoice" && doc.extraction && doc.is_current && !doc.duplicate_of_id && <Simulator doc={doc} />}
          <ProcessingDetails key={JSON.stringify(doc.overrides)} doc={doc} onChanged={reload} />
          {doc.extraction && (
            <Timeline docId={doc.id} version={`${doc.findings.length}-${doc.corrections.length}-${doc.links.map((l) => l.status).join()}`} />
          )}
        </div>
        <Viewer doc={doc} />
      </div>
    </>
  );
}
