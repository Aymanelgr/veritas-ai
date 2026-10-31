import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listDocuments } from "../api.js";
import Badge from "../components/Badge.jsx";
import Upload from "../components/Upload.jsx";
import { relativeTime } from "../format.js";
import { IconChevron, IconFile, IconSearch } from "../icons.jsx";
import usePolling, { isBusy } from "../usePolling.js";

const anyBusy = (docs) => docs.some((d) => isBusy(d.status));
const FILTERS = [
  ["all", "All"],
  ["invoice", "Invoices"],
  ["purchase_order", "Purchase orders"],
  ["issues", "With open issues"],
];

export default function Documents() {
  const { data: docs, error, reload } = usePolling(listDocuments, anyBusy);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const navigate = useNavigate();

  const shown = useMemo(() => (docs ?? []).filter((d) => {
    const text = `${d.filename} ${d.number ?? ""}`.toLowerCase();
    const kind = filter === "all" || (filter === "issues" ? d.open_findings > 0 : d.doc_type === filter);
    return kind && text.includes(query.trim().toLowerCase());
  }), [docs, query, filter]);

  if (error) return <p className="error">Cannot load documents.</p>;
  if (!docs) return <div className="skeleton" style={{ height: 200 }} />;

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Documents</h1>
          <p>{docs.length} document{docs.length === 1 ? "" : "s"}. Processing runs in the background; this list updates itself.</p>
        </div>
      </header>
      <Upload onUploaded={reload} />

      <div className="toolbar">
        <label className="search-field">
          <IconSearch size={16} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by file name or number" />
        </label>
        <div className="tabs">
          {FILTERS.map(([value, label]) => (
            <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
      </div>

      <section className="panel panel-flush rise">
        <table className="clickable">
          <thead>
            <tr>
              <th>File</th><th>Type</th><th>Number</th><th>Status</th><th>Open issues</th><th>Uploaded</th><th />
            </tr>
          </thead>
          <tbody>
            {shown.map((d, i) => (
              // The whole row opens the document; Enter works too for keyboard users.
              <tr key={d.id} className="fade-row" style={{ "--i": i }} tabIndex={0}
                  onClick={() => navigate(`/documents/${d.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/documents/${d.id}`)}>
                <td><span className="file-cell"><IconFile size={16} />{d.filename}</span></td>
                <td><Badge value={d.doc_type} /></td>
                <td>{d.number ?? <span className="muted">—</span>}</td>
                <td><Badge value={d.status} /></td>
                <td>{d.open_findings ? <Badge value="critical" label={`${d.open_findings} open`} /> : <span className="muted">None</span>}</td>
                <td className="muted">{relativeTime(d.created_at)}</td>
                <td><IconChevron size={16} className="chevron" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && (
          <p className="empty">{docs.length ? "No documents match this filter." : "No documents yet. Upload a purchase order and an invoice."}</p>
        )}
      </section>
    </>
  );
}
