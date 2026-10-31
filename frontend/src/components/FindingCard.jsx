import { forwardRef, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, reviewFinding } from "../api.js";
import { IconAlert, IconCheck, IconQuestion } from "../icons.jsx";
import { useToast } from "../toast.jsx";
import Badge from "./Badge.jsx";
import { can, useUser } from "../user.js";

const VERDICT_ICON = { supported: IconCheck, contradicted: IconAlert, insufficient_evidence: IconQuestion };

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
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const Icon = VERDICT_ICON[finding.verdict] ?? IconQuestion;
  const evidence = finding.evidence.filter((e) => e.source_line);

  async function decide(decision) {
    if (busy) return;
    setBusy(true);
    try {
      await reviewFinding(finding.id, decision, note || null);
      toast(decision === "approved" ? "Issue confirmed" : "Marked as a false alarm", {
        tone: decision === "approved" ? "critical" : "ok",
        action: {
          label: "Undo",
          onClick: () => reviewFinding(finding.id, "pending").then(() => onChanged?.()),
        },
      });
      if (removeOnReview) setLeaving(true); // onChanged runs when the animation ends
      else onChanged?.();
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setBusy(false);
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
          <Badge value={finding.verdict} />
          <span className="spacer" />
          {showDocument && (
            <Link to={`/documents/${finding.document_id}`} className="small">{finding.document_filename}</Link>
          )}
        </div>
        <h3>{finding.claim}</h3>
        <p>{finding.explanation}</p>

        {evidence.length > 0 && (
          <div className="evidence">
            {evidence.map((e, i) => (
              <div key={i}>
                <span>Evidence · {e.document}</span>
                <code>{e.source_line}</code>
              </div>
            ))}
          </div>
        )}

        {finding.review_status === "pending" && can(user, "reviewer") && (
          <div className="review">
            <input placeholder="Add a note for the record (optional)" value={note}
                   onChange={(e) => setNote(e.target.value)} />
            <button className="danger" disabled={busy} onClick={() => decide("approved")} title="The problem is real (C)">
              Confirm issue
            </button>
            <button disabled={busy} onClick={() => decide("rejected")} title="False alarm (D)">
              Dismiss
            </button>
          </div>
        )}
        {(finding.review_status === "approved" || finding.review_status === "rejected") && (
          <div className="reviewed">
            <Badge value={finding.review_status} /> by reviewer
            {finding.reviewer_note && <span>· “{finding.reviewer_note}”</span>}
          </div>
        )}
      </div>
    </article>
  );
});

export default FindingCard;
