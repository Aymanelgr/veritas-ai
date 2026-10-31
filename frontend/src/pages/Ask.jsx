import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { askQuestion, errorMessage } from "../api.js";
import Badge from "../components/Badge.jsx";
import { IconSend } from "../icons.jsx";
import { useReveal } from "../motion.js";

const EXAMPLES = [
  "How many hydraulic pumps were ordered and how many were invoiced?",
  "When is the invoice payment due?",
  "What are the payment terms of the purchase order?",
];

function Answer({ result }) {
  const [flash, setFlash] = useState(null);
  const sources = useRef({});
  // Words and [n] citation markers become tokens that appear one after another.
  const tokens = result.answer.split(/(\[\d+\]|\s+)/g).filter(Boolean);
  const shown = useReveal(tokens.length);
  const done = shown >= tokens.length;
  const cited = new Set(result.checks.flatMap((c) => c.citations));
  const accuracy = result.citation_accuracy;

  function showSource(n) {
    sources.current[n]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFlash(n);
    setTimeout(() => setFlash(null), 1200);
  }

  return (
    <div className="bubble-a">
      <div className="panel">
        <p className="answer-text">
          {tokens.slice(0, shown).map((t, i) => {
            const match = /^\[(\d+)\]$/.exec(t);
            return match
              ? <button key={i} className="cite" onClick={() => showSource(Number(match[1]))}
                        title="Show this source">{match[1]}</button>
              : <span key={i}>{t}</span>;
          })}
          {!done && <span className="caret" />}
        </p>
        <div className={`fade-in-after ${done ? "visible" : ""}`}>
          {accuracy != null && (
            <Badge value={accuracy === 1 ? "supported" : "insufficient_evidence"}
                   label={accuracy === 1 ? "Every statement is backed by its citation"
                     : `${Math.round(accuracy * 100)}% of statements backed by their citations`} />
          )}
          {result.checks.filter((c) => c.verdict !== "supported").map((c, i) => (
            <p key={i} className="error small">Not backed by its cited source: “{c.sentence}”</p>
          ))}
          {result.sources.length > 0 && (
            <div className="sources">
              {result.sources.map((s) => (
                <div key={s.n} ref={(el) => (sources.current[s.n] = el)}
                     className={`source ${cited.has(s.n) ? "cited" : ""} ${flash === s.n ? "flash" : ""}`}>
                  <span className="cite">{s.n}</span> <strong>{s.label}</strong>
                  <div className="muted small">{s.filename}, page {s.page}</div>
                  <pre>{s.text}</pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Ask() {
  const [params] = useSearchParams();
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]); // [{question, result}]
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const asked = useRef(false);
  const bottom = useRef(null);

  async function submit(text) {
    if (!text.trim() || pending) return;
    setPending(text);
    setError(null);
    setQuestion("");
    try {
      const result = await askQuestion(text);
      setHistory((h) => [...h, { question: text, result }]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(null);
    }
  }

  // /ask?q=... asks immediately, so questions can be shared as links.
  useEffect(() => {
    const q = params.get("q");
    if (q && !asked.current) {
      asked.current = true;
      submit(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.length, pending]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1>Ask your documents</h1>
          <p>Answers come only from your uploaded documents, with numbered citations. Each one is checked automatically.</p>
        </div>
      </header>

      <form className="ask-bar" onSubmit={(e) => { e.preventDefault(); submit(question); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} autoFocus
               placeholder="e.g. What is the total amount due on the invoice?" disabled={!!pending} />
        <button type="submit" className="primary" disabled={!!pending || !question.trim()}>
          <IconSend size={16} /> Ask
        </button>
      </form>
      {history.length === 0 && !pending && (
        <div className="chips">
          {EXAMPLES.map((q, i) => (
            <button key={q} className="chip rise" style={{ "--i": i }} onClick={() => submit(q)}>{q}</button>
          ))}
        </div>
      )}
      {error && <p className="error">{error}</p>}

      <div className="chat">
        {history.map(({ question: q, result }, i) => (
          <div key={i} className="chat">
            <div className="bubble-q">{q}</div>
            <Answer result={result} />
          </div>
        ))}
        {pending && (
          <>
            <div className="bubble-q">{pending}</div>
            <div className="bubble-a"><div className="panel thinking"><span className="typing"><i /><i /><i /></span>
              <span className="muted small"> Searching your documents and writing an answer…</span></div></div>
          </>
        )}
        <div ref={bottom} />
      </div>
    </>
  );
}
