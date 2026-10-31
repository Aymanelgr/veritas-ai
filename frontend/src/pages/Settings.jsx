import { useEffect, useState } from "react";
import { errorMessage, getAlertSettings, listDeliveries, saveAlertSettings, sendTestAlert } from "../api.js";
import Badge from "../components/Badge.jsx";
import { relativeTime } from "../format.js";
import { useToast } from "../toast.jsx";

const MODES = [
  ["off", "Off", "Alerts appear in the Veritas inbox only."],
  ["preview", "Preview", "Emails are prepared and listed below, but never sent. Use this to check the content."],
  ["send", "Send", "n8n emails the recipients. Requires SMTP credentials in n8n and the email node enabled."],
];
const STATUS_TONE = { sent: "supported", preview: "info", handed_off: "processing", queued: "uploaded",
  failed: "failed", skipped: "insufficient_evidence" };

export default function Settings() {
  const toast = useToast();
  const [settings, setSettings] = useState(null);
  const [recipients, setRecipients] = useState("");
  const [deliveries, setDeliveries] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const loadDeliveries = () => listDeliveries().then(setDeliveries, () => {});
  useEffect(() => {
    getAlertSettings().then((s) => {
      setSettings(s);
      setRecipients(s.recipients.join(", "));
    }, (err) => setError(errorMessage(err)));
    loadDeliveries();
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const saved = await saveAlertSettings({
        ...settings, recipients: recipients.split(/[,;\s]+/).map((r) => r.trim()).filter(Boolean),
      });
      setSettings(saved);
      setRecipients(saved.recipients.join(", "));
      toast("Alert settings saved", { tone: "ok" });
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    try {
      const d = await sendTestAlert();
      toast(d.status === "skipped" ? d.last_error : `Test alert ${d.status === "failed" ? "failed: " + d.last_error : "handed to n8n"}`,
            { tone: d.status === "failed" ? "critical" : "info" });
      setTimeout(loadDeliveries, 1500);
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!settings) return <div className="skeleton" style={{ height: 200 }} />;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Mismatch alerts, summaries and reminders. Emails contain a short summary and a link that requires
            sign-in; documents are never attached.</p>
        </div>
      </header>

      <form className="panel settings" onSubmit={save}>
        <h2>Alerts</h2>
        {!settings.webhook_configured && (
          <p className="notice">N8N_WEBHOOK_URL is not set on the server, so alerts stay inside Veritas.</p>
        )}
        <fieldset>
          <legend>Email</legend>
          {MODES.map(([value, label, help]) => (
            <label key={value} className="radio">
              <input type="radio" name="mode" value={value} checked={settings.email_mode === value}
                     onChange={() => setSettings({ ...settings, email_mode: value })} />
              <span><strong>{label}</strong> <span className="muted small">{help}</span></span>
            </label>
          ))}
        </fieldset>
        <label className="stacked">
          <span>Recipients</span>
          <input value={recipients} onChange={(e) => setRecipients(e.target.value)}
                 placeholder="reviewer@company.com, finance@company.com" />
        </label>
        <label className="stacked">
          <span>Alert when a new finding is</span>
          <select value={settings.min_severity} onChange={(e) => setSettings({ ...settings, min_severity: e.target.value })}>
            <option value="critical">Critical only</option>
            <option value="warning">Critical or warning</option>
          </select>
        </label>
        <p className="muted small">Each finding is alerted at most once. Daily reminders list findings waiting more than a
          day; each organization gets at most one reminder per day.</p>
        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>Save</button>
          <button type="button" onClick={test}>Send a test alert</button>
        </div>
      </form>

      <section className="panel panel-flush" style={{ marginTop: "1.5rem" }}>
        <div className="panel-header">
          <h2>Recent alerts</h2>
          <button className="link small" onClick={loadDeliveries}>Refresh</button>
        </div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>When</th><th>Kind</th><th>Status</th><th>Summary</th><th>Recipients</th></tr></thead>
            <tbody>
              {deliveries.map((d) => (
                <tr key={d.id}>
                  <td className="muted small">{relativeTime(d.created_at)}</td>
                  <td>{d.kind}</td>
                  <td><Badge value={STATUS_TONE[d.status] ?? "info"} label={d.status.replace("_", " ")} />
                    {d.last_error && <div className="muted small">{d.last_error}</div>}</td>
                  <td>{d.summary}</td>
                  <td className="small">{(d.recipients ?? []).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {deliveries.length === 0 && <p className="empty small">No alerts yet.</p>}
      </section>

      <section className="panel" style={{ marginTop: "1.5rem" }}>
        <h2>Email intake (optional)</h2>
        <p className="muted small">Veritas can import invoices and orders attached to emails sent to a designated mailbox.
          It is off until configured in <code>.env</code> and run with <code>python scripts/mail_intake.py</code>
          (a dry run by default; the mailbox is only ever read, never changed). Repeated emails and attachments
          already received are skipped. See the README for setup.</p>
      </section>
    </>
  );
}
