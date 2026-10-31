import { useCallback, useEffect, useRef, useState } from "react";
import { listFindings } from "../api.js";
import FindingCard from "../components/FindingCard.jsx";
import { IconCheck } from "../icons.jsx";
import usePolling from "../usePolling.js";

const FILTERS = [
  ["pending", "Awaiting review"],
  ["approved", "Confirmed"],
  ["rejected", "Dismissed"],
];

export default function Reviews() {
  const [status, setStatus] = useState("pending");
  const [active, setActive] = useState(0);
  const [command, setCommand] = useState(null);
  const cards = useRef([]);
  const loader = useCallback(() => listFindings({ review_status: status }), [status]);
  const { data: findings, error, reload } = usePolling(loader);
  const count = findings?.length ?? 0;

  // Keyboard review: J/K or arrows move, C confirms, D dismisses.
  useEffect(() => {
    const onKey = (e) => {
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName) || e.ctrlKey || e.metaKey || !count) return;
      const key = e.key.toLowerCase();
      if (key === "j" || key === "arrowdown") setActive((a) => Math.min(a + 1, count - 1));
      else if (key === "k" || key === "arrowup") setActive((a) => Math.max(a - 1, 0));
      else if (status === "pending" && (key === "c" || key === "d"))
        setCommand({ decision: key === "c" ? "approved" : "rejected", at: Date.now() });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [count, status]);

  useEffect(() => {
    cards.current[active]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(count - 1, 0)));
  }, [count]);

  // Deliver a keyboard command once, then clear it. Otherwise the next card to become
  // active would receive the same old command and be decided by accident.
  useEffect(() => {
    if (!command) return undefined;
    const timer = setTimeout(() => setCommand(null), 0);
    return () => clearTimeout(timer);
  }, [command]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Human review</h1>
          <p>Veritas flags problems with evidence; you decide. Confirm real issues, dismiss false alarms.</p>
        </div>
        {status === "pending" && count > 0 && (
          <p className="shortcuts muted small">
            <kbd>J</kbd><kbd>K</kbd> move · <kbd>C</kbd> confirm · <kbd>D</kbd> dismiss
          </p>
        )}
      </header>
      <div className="tabs">
        {FILTERS.map(([value, label]) => (
          <button key={value} className={status === value ? "active" : ""}
                  onClick={() => { setStatus(value); setActive(0); }}>
            {label}
          </button>
        ))}
      </div>
      {error && <p className="error">Cannot load findings.</p>}
      {!findings && !error && <div className="skeleton" style={{ height: 120 }} />}
      {findings?.length === 0 && (
        <div className="panel empty rise"><IconCheck size={32} /><p>Nothing here. You're all caught up.</p></div>
      )}
      {findings?.map((f, i) => (
        <FindingCard key={f.id} ref={(el) => (cards.current[i] = el)} finding={f} showDocument
                     removeOnReview active={i === active} command={i === active ? command : null}
                     onChanged={reload} style={{ "--i": i }} />
      ))}
    </>
  );
}
