import { forwardRef, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { attachEvidence, draftClarification, errorMessage, explainFinding, reviewFinding } from "../api.js";
import { money } from "../format.js";
import { IconAlert, IconCheck, IconQuestion } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import Badge from "./Badge.jsx";
import { can, useUser } from "../user.js";

const VERDICT_ICON = { supported: IconCheck, contradicted: IconAlert, insufficient_evidence: IconQuestion };
// A reading problem is not an accounting problem, and a check that could not run is not a pass.
const KIND = {
  possible_reading_error: ["Possible reading error", "warning"],
  not_checked: ["Could not be checked", "insufficient_evidence"],
};
const DECIDED = {
  approved: "Issue confirmed (this does not approve the invoice for payment)",
  rejected: "Dismissed as a false alarm",
  resolved: "Marked resolved",
  superseded: "Decided on earlier evidence that has since changed",
};
const TOASTS = { approved: ["Issue confirmed", "critical"], rejected: ["Marked as a false alarm", "ok"], resolved: ["Marked resolved", "ok"] };

function Explanation({ data }) {
  return (
    <div className="explain">
      <p>{data.summary}</p>
      {data.compared?.length > 0 && (
        <ul>{data.compared.map((c, i) => <li key={i}>{c}</li>)}</ul>
      )}
      {data.what_would_resolve?.length > 0 && (
        <>
          <strong className="small">What would settle it</strong>
          <ul>{data.what_would_resolve.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </>
      )}
      {data.history?.length > 0 && (
        <>
          <strong className="small">History</strong>
          <ul className="small">{data.history.map((h, i) => <li key={i}>{new Date(h.at).toLocaleString()} · {h.text}</li>)}</ul>
        </>
      )}
      <p className="muted small">Rules {data.rule_version ?? "unknown"} · {Object.entries(data.model_versions ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
    </div>
  );
}

function Draft({ draft }) {
  const toast = useToast();
  const text = `Subject: ${draft.subject}\n\n${draft.body}`;
  return (
    <div className="explain">
      <p className="muted small">A draft for you to review and send yourself. Veritas does not send it.
        {draft.to ? ` Suggested recipient: ${draft.to}.` : ""}</p>
      <textarea readOnly value={text} rows={Math.min(16, text.split("\n").length + 1)} dir="auto" aria-label="Draft message" />
      <button onClick={() => navigator.clipboard?.writeText(text).then(() => toast("Draft copied", { tone: "ok" }),
        () => toast("Copy failed: select the text and copy it", { tone: "critical" }))}>Copy draft</button>
    </div>
  );
}

/**
 * One verification result with its evidence and the review buttons.
 *  removeOnReview  collapse the card away after a decision (review queues)
 *  onChanged       called after a decision or an undo, to reload data
 *  command         {decision, at}: lets a parent trigger a decision from the keyboard
 */
const FindingCard = forwardRef(function FindingCard(
  { finding, onChanged, showDocument = false, removeOnReview = false, active = false,
    highlighted = false, command, onHover, style },
  ref,
) {
  const toast = useToast();
  const user = useUser();
  const [note, setNote] = useState("");
  const [evidenceText, setEvidenceText] = useState("");
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [panel, setPanel] = useState(null); // null | "explain" | "draft" | "attach"
  const [explanation, setExplanation] = useState(null);
  const [draft, setDraft] = useState(null);
  const Icon = VERDICT_ICON[finding.verdict] ?? IconQuestion;
  const evidence = finding.evidence.filter((e) => e.source_line);
  const kind = KIND[finding.kind];
  const reviewer = can(user, "reviewer");
  const isProblem = finding.verdict !== "supported";

  async function decide(decision) {
    if (busy) return;
    setBusy(true);
    try {
      await reviewFinding(finding.id, decision, note || null);
      const [message, tone] = TOASTS[decision];
      toast(message, {
        tone,
        action: { label: "Undo", onClick: () => reviewFinding(finding.id, "pending").then(() => onChanged?.()) },
      });
      if (removeOnReview) setLeaving(true); // onChanged runs when the animation ends
      else onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
    }
  }

  async function toggle(name) {
    if (panel === name) return setPanel(null);
    setPanel(name);
    try {
      if (name === "explain" && !explanation) setExplanation(await explainFinding(finding.id));
      if (name === "draft" && !draft) setDraft(await draftClarification(finding.id));
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
      setPanel(null);
    }
  }

  async function attach(e) {
    e.preventDefault();
    if (!evidenceText.trim()) return;
    try {
      await attachEvidence(finding.id, evidenceText);
      setEvidenceText("");
      setPanel(null);
      toast("Evidence attached", { tone: "ok" });
      onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    }
  }

  // Keyboard shortcuts from the Reviews page arrive as a command with a timestamp.
  useEffect(() => {
    if (command && active && finding.review_status === "pending") decide(command.decision);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [command]);

  return (
    <article
      ref={ref}
      style={style}
      className={`finding finding-${finding.severity} ${leaving ? "leaving" : ""} ${active ? "active" : ""} ${highlighted ? "highlighted" : ""}`}
      onAnimationEnd={(e) => e.animationName === "collapse-out" && onChanged?.()}
      onMouseEnter={() => onHover?.(finding)}
      onMouseLeave={() => onHover?.(null)}
    >
      <span className="finding-icon"><Icon size={22} /></span>
      <div className="finding-body">
        <div className="finding-meta">
          <Badge value={finding.severity} />
          {kind ? <Badge value={kind[1]} label={kind[0]} /> : <Badge value={finding.verdict} />}
          {finding.impact != null && Number(finding.impact) !== 0 && (
            <span className="impact">Impact {money(finding.impact, finding.currency)}</span>
          )}
          <span className="spacer" />
          {showDocument && (
            <Link to={`/documents/${finding.document_id}`} className="small">{finding.document_filename}</Link>
          )}
        </div>
        <h3 dir="auto">{finding.claim}</h3>
        <p dir="auto">{finding.explanation}</p>

        {evidence.length > 0 && (
          <div className="evidence">
            {evidence.map((e, i) => (
              <div key={i}>
                <span>Evidence · {e.document}{e.page ? `, page ${e.page}` : ""}</span>
                <code dir="auto">{e.source_line}</code>
              </div>
            ))}
          </div>
        )}

        {finding.attachments?.length > 0 && (
          <ul className="attachments">
            {finding.attachments.map((a, i) => (
              <li key={i}><span dir="auto">{a.text}</span> <span className="muted small">· {a.by}, {new Date(a.at).toLocaleDateString()}</span></li>
            ))}
          </ul>
        )}

        {isProblem && (
          <div className="finding-tools">
            <button className="link small" onClick={() => toggle("explain")} aria-expanded={panel === "explain"}>Explain this finding</button>
            {reviewer && <button className="link small" onClick={() => toggle("draft")} aria-expanded={panel === "draft"}>Draft supplier message</button>}
            {reviewer && <button className="link small" onClick={() => toggle("attach")} aria-expanded={panel === "attach"}>Attach evidence</button>}
          </div>
        )}
        {panel === "explain" && (explanation ? <Explanation data={explanation} /> : <div className="skeleton" />)}
        {panel === "draft" && (draft ? <Draft draft={draft} /> : <div className="skeleton" />)}
        {panel === "attach" && (
          <form className="review" onSubmit={attach}>
            <input autoFocus placeholder="e.g. Email from the buyer on 10 Oct approving 3 pumps" value={evidenceText}
                   onChange={(e) => setEvidenceText(e.target.value)} aria-label="Evidence description" />
            <button type="submit" disabled={!evidenceText.trim()}>Attach</button>
          </form>
        )}

        {finding.review_status === "pending" && reviewer && (
          <div className="review">
            <input placeholder="Add a note for the record (optional)" value={note}
                   onChange={(e) => setNote(e.target.value)} aria-label="Review note" />
            <button className="danger" disabled={busy} onClick={() => decide("approved")}
                    title="The problem is real (C). This does not approve the invoice for payment.">
              Confirm issue
            </button>
            <button disabled={busy} onClick={() => decide("resolved")} title="Fixed, e.g. by a credit note or a correction">
              Mark resolved
            </button>
            <button disabled={busy} onClick={() => decide("rejected")} title="False alarm (D)">
              Dismiss
            </button>
          </div>
        )}
        {DECIDED[finding.review_status] && (
          <div className="reviewed">
            <Badge value={finding.review_status} /> {DECIDED[finding.review_status]}
            {finding.reviewer_note && <span>· “{finding.reviewer_note}”</span>}
            {reviewer && finding.review_status !== "superseded" && (
              <button className="link small" onClick={() => reviewFinding(finding.id, "pending").then(() => onChanged?.())}>Reopen</button>
            )}
          </div>
        )}
      </div>
    </article>
  );
});

export default FindingCard;
