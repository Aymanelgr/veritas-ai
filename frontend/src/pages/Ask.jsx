import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  askQuestion, deleteConversation, errorMessage, getConversation, listConversations, listDocuments,
} from "../api.js";
import Badge from "../components/Badge.jsx";
import { relativeTime } from "../format.js";
import { IconSend, IconTrash } from "../icons.jsx";
import { useReveal } from "../motion.js";

const EXAMPLES = [
  "How many hydraulic pumps were ordered and how many were invoiced?",
  "When is the invoice payment due?",
  "Which invoices are not matched to a purchase order?",
  "How many findings await review?",
];

function DatabaseAnswer({ result }) {
  return (
    <div className="bubble-a">
      <div className="panel">
        <p className="answer-text">{result.answer}</p>
        <Badge value="supported" label="Exact figures from the Veritas database" />
        {result.records?.length > 0 && (
          <ul className="records">
            {result.records.map((r) => (
              <li key={r.document_id}>
                <Link to={`/documents/${r.document_id}`}>{r.label}</Link>
                {r.detail && <span className="muted small"> · {r.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function DocumentAnswer({ result, animate }) {
  const [flash, setFlash] = useState(null);
  const sources = useRef({});
  // Words and [n] citation markers become tokens that appear one after another.
  const tokens = result.answer.split(/(\[\d+\]|\s+)/g).filter(Boolean);
  const revealed = useReveal(tokens.length);
  const shown = animate ? revealed : tokens.length;
  const done = shown >= tokens.length;
  const cited = new Set(result.checks.flatMap((c) => c.citations));
  const accuracy = result.citation_accuracy;
  const unsupported = result.unsupported ?? (!result.sources.length || (accuracy != null && accuracy < 1));

  function showSource(n) {
    sources.current[n]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFlash(n);
    setTimeout(() => setFlash(null), 1200);
  }

  return (
    <div className="bubble-a">
      <div className="panel">
        <p className="answer-text" dir="auto">
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
          {unsupported && (
            <p className="notice small">Not fully supported by your documents. Check the sources before relying on this answer.</p>
          )}
          {result.checks.filter((c) => c.verdict !== "supported").map((c, i) => (
            <p key={i} className="error small">Not backed by its cited source: “{c.sentence}”</p>
          ))}
          {result.redacted && <p className="muted small">Some sources were removed because their documents were deleted.</p>}
          {result.sources.length > 0 && (
            <div className="sources">
              {result.sources.map((s) => (
                <div key={s.n} ref={(el) => (sources.current[s.n] = el)}
                     className={`source ${cited.has(s.n) ? "cited" : ""} ${flash === s.n ? "flash" : ""}`}>
                  <span className="cite">{s.n}</span> <Link to={`/documents/${s.document_id}`}><strong>{s.label}</strong></Link>
                  <div className="muted small">{s.filename}, page {s.page}</div>
                  <pre dir="auto">{s.text}</pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Scope({ documents, selected, onChange, locked }) {
  const [open, setOpen] = useState(false);
  const names = documents.filter((d) => selected.includes(d.id)).map((d) => d.number ?? d.filename);
  return (
    <div className="scope">
      <button type="button" className="link small" onClick={() => setOpen(!open)} aria-expanded={open} disabled={locked}>
        Searching: {names.length ? names.join(", ") : "all documents"}{locked ? "" : " · change"}
      </button>
      {open && !locked && (
        <div className="scope-list">
          {documents.filter((d) => !d.duplicate_of_id).map((d) => (
            <label key={d.id}>
              <input type="checkbox" checked={selected.includes(d.id)}
                     onChange={(e) => onChange(e.target.checked ? [...selected, d.id] : selected.filter((x) => x !== d.id))} />
              {d.number ?? d.filename} <span className="muted small">{d.doc_type?.replace("_", " ")}</span>
            </label>
          ))}
          {selected.length > 0 && <button type="button" className="link small" onClick={() => onChange([])}>Search all documents</button>}
        </div>
      )}
    </div>
  );
}

export default function Ask() {
  const [params, setParams] = useSearchParams();
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState(null);
  const [history, setHistory] = useState([]); // [{question, result, fresh}]
  const [conversations, setConversations] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [scope, setScope] = useState([]);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const asked = useRef(false);
  const bottom = useRef(null);

  const loadConversations = useCallback(() => listConversations().then(setConversations, () => {}), []);
  useEffect(() => {
    loadConversations();
    listDocuments().then(setDocuments, () => {});
    // /ask?document=12 starts a conversation limited to that document.
    const doc = Number(params.get("document"));
    if (doc) setScope([doc]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(text) {
    if (!text.trim() || pending) return;
    setPending(text);
    setError(null);
    setQuestion("");
    try {
      const result = await askQuestion(text, { conversationId, documentIds: conversationId ? null : scope });
      setConversationId(result.conversation_id);
      setHistory((h) => [...h, { question: text, result, fresh: true }]);
      loadConversations();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(null);
    }
  }

  async function open(id) {
    try {
      const c = await getConversation(id);
      setConversationId(c.id);
      setScope(c.document_ids ?? []);
      setHistory(c.messages.map((m) => ({ question: m.question, result: m.answer, fresh: false })));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function startNew() {
    setConversationId(null);
    setHistory([]);
    setScope([]);
    setParams({});
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
          <p>Counts and statuses come straight from the database. Questions about document content are answered
            only from your documents, with numbered citations that are checked automatically.</p>
        </div>
        {conversationId && <button className="ghost" onClick={startNew}>New conversation</button>}
      </header>

      <div className="ask-layout">
        <div>
          <form className="ask-bar" onSubmit={(e) => { e.preventDefault(); submit(question); }}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} autoFocus
                   placeholder={history.length ? "Ask a follow-up question…" : "e.g. What is the total amount due on the invoice?"}
                   disabled={!!pending} aria-label="Question" />
            <button type="submit" className="primary" disabled={!!pending || !question.trim()}>
              <IconSend size={16} /> Ask
            </button>
          </form>
          <Scope documents={documents} selected={scope} onChange={setScope} locked={!!conversationId} />
          {history.length === 0 && !pending && (
            <div className="chips">
              {EXAMPLES.map((q, i) => (
                <button key={q} className="chip rise" style={{ "--i": i }} onClick={() => submit(q)}>{q}</button>
              ))}
            </div>
          )}
          {error && <p className="error">{error}</p>}

          <div className="chat">
            {history.map(({ question: q, result, fresh }, i) => (
              <div key={i} className="chat">
                <div className="bubble-q" dir="auto">{q}</div>
                {result.kind === "database"
                  ? <DatabaseAnswer result={result} />
                  : <DocumentAnswer result={result} animate={fresh} />}
              </div>
            ))}
            {pending && (
              <>
                <div className="bubble-q">{pending}</div>
                <div className="bubble-a"><div className="panel thinking"><span className="typing"><i /><i /><i /></span>
                  <span className="muted small"> Looking it up…</span></div></div>
              </>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <aside className="panel panel-flush conversations">
          <div className="panel-header"><h2>Saved conversations</h2></div>
          {conversations.length === 0 && <p className="empty small">Your conversations are saved here. Only you can see them.</p>}
          <ul>
            {conversations.map((c) => (
              <li key={c.id} className={c.id === conversationId ? "active" : ""}>
                <button className="conversation" onClick={() => open(c.id)}>
                  <span dir="auto">{c.title}</span>
                  <span className="muted small">{relativeTime(c.updated_at ?? c.created_at)}</span>
                </button>
                <button className="ghost icon-only" title="Delete conversation" aria-label={`Delete conversation ${c.title}`}
                        onClick={() => deleteConversation(c.id).then(() => {
                          if (c.id === conversationId) startNew();
                          loadConversations();
                        })}><IconTrash size={14} /></button>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </>
  );
}
