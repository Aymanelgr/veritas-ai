import { useCallback } from "react";
import { Link } from "react-router-dom";
import { getStats, listDocuments, listFindings, listNotifications } from "../api.js";
import Badge from "../components/Badge.jsx";
import FindingCard from "../components/FindingCard.jsx";
import Inbox from "../components/Inbox.jsx";
import Upload from "../components/Upload.jsx";
import { IconAlert, IconCheck, IconChevron, IconClock, IconFile, IconReview } from "../icons.jsx";
import { useCountUp } from "../motion.js";
import usePolling, { isBusy } from "../usePolling.js";

const loadDashboard = () =>
  Promise.all([getStats(), listDocuments(), listFindings({ severity: "critical" }), listNotifications()]).then(
    ([stats, documents, critical, notifications]) => ({ stats, documents, critical, notifications }),
  );
const anyBusy = (data) => data.stats.processing > 0;

function StatCard({ label, value, icon: Icon, tone, to, index }) {
  const shown = useCountUp(value);
  const body = (
    <>
      <span className="stat-icon"><Icon size={20} /></span>
      <div>
        <div className="stat-value">{shown}</div>
        <div className="stat-label">{label}</div>
      </div>
    </>
  );
  const props = { className: `stat ${tone} rise`, style: { "--i": index } };
  return to ? <Link to={to} {...props}>{body}</Link> : <div {...props}>{body}</div>;
}

export default function Dashboard() {
  const loader = useCallback(loadDashboard, []);
  const { data, error, reload } = usePolling(loader, anyBusy);

  if (error) return <p className="error">Cannot reach the backend. Is the API running on port 8000?</p>;
  if (!data) return <div className="skeleton" style={{ height: 120 }} />;
  const { stats } = data;

  const cards = [
    { label: "Documents", value: stats.documents, icon: IconFile, tone: "", to: "/documents" },
    { label: "Processing", value: stats.processing, icon: IconClock, tone: stats.processing ? "warning" : "" },
    { label: "Critical issues open", value: stats.critical_open, icon: IconAlert,
      tone: `critical ${stats.critical_open ? "active" : ""}`, to: "/reviews" },
    { label: "Awaiting review", value: stats.pending_reviews, icon: IconReview,
      tone: stats.pending_reviews ? "warning" : "", to: "/reviews" },
    { label: "Reviews completed", value: stats.approved + stats.rejected, icon: IconCheck, tone: "ok" },
  ];

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Upload documents; Veritas reads, links and verifies them, and flags what needs a human.</p>
        </div>
      </header>

      <section className="stats">
        {cards.map((card, i) => <StatCard key={card.label} index={i} {...card} />)}
      </section>

      <Upload onUploaded={reload} />

      <div className="columns">
        <section>
          <h2><IconAlert /> Critical issues awaiting review</h2>
          {data.critical.length === 0 && (
            <div className="panel empty rise"><IconCheck size={32} /><p>Nothing critical is waiting.</p></div>
          )}
          {data.critical.map((f, i) => (
            <FindingCard key={f.id} finding={f} showDocument removeOnReview onChanged={reload}
                         style={{ "--i": i }} />
          ))}
        </section>

        <div className="stack">
          <Inbox notifications={data.notifications} onChange={reload} />
          <section className="panel panel-flush rise" style={{ "--i": 2 }}>
            <div className="panel-header">
              <h2><IconFile /> Recent documents</h2>
              <Link to="/documents" className="small">View all</Link>
            </div>
            <ul className="doc-list">
              {data.documents.slice(0, 6).map((d) => (
                <li key={d.id}>
                  <Link to={`/documents/${d.id}`} className="row-link">
                    <span className="file-cell"><IconFile size={16} />{d.filename}</span>
                    <span>
                      {d.open_findings > 0 && <Badge value="critical" label={`${d.open_findings} open`} />}{" "}
                      <Badge value={isBusy(d.status) || d.status === "failed" ? d.status : d.doc_type} />
                      <IconChevron size={16} className="chevron" />
                    </span>
                  </Link>
                </li>
              ))}
              {data.documents.length === 0 && <li className="muted">No documents yet.</li>}
            </ul>
          </section>
        </div>
      </div>
    </>
  );
}
