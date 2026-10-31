import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listDocuments } from "../api.js";
import { docTypeLabel } from "../format.js";
import { IconChat, IconDashboard, IconFile, IconReview, IconSearch } from "../icons.jsx";

const PAGES = [
  { label: "Dashboard", to: "/", icon: IconDashboard },
  { label: "Documents", to: "/documents", icon: IconFile },
  { label: "Reviews", to: "/reviews", icon: IconReview },
  { label: "Ask your documents", to: "/ask", icon: IconChat },
];

// Ctrl+K (or "/") opens a search box to jump to any page or document.
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [docs, setDocs] = useState([]);
  const [active, setActive] = useState(0);
  const input = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e) => {
      const typing = ["INPUT", "TEXTAREA"].includes(e.target.tagName);
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    listDocuments().then(setDocs, () => setDocs([]));
    setTimeout(() => input.current?.focus(), 0);
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const documents = docs.map((d) => ({
      label: d.number ?? d.filename, hint: `${docTypeLabel(d.doc_type)} · ${d.filename}`,
      to: `/documents/${d.id}`, icon: IconFile,
    }));
    const ask = q ? [{ label: `Ask: “${query}”`, to: `/ask?q=${encodeURIComponent(query)}`, icon: IconChat }] : [];
    const match = (item) => `${item.label} ${item.hint ?? ""}`.toLowerCase().includes(q);
    return [...PAGES.filter(match), ...documents.filter(match), ...ask].slice(0, 9);
  }, [query, docs]);

  function go(item) {
    setOpen(false);
    if (item) navigate(item.to);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    if (e.key === "Enter") go(results[active]);
    if (e.key === "Escape") setOpen(false);
  }

  if (!open) return null;
  return (
    <div className="overlay" onMouseDown={() => setOpen(false)}>
      <div className="palette" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Search">
        <div className="palette-input">
          <IconSearch />
          <input ref={input} value={query} placeholder="Search pages and documents, or ask a question…"
                 onChange={(e) => { setQuery(e.target.value); setActive(0); }} onKeyDown={onKeyDown} />
          <kbd>Esc</kbd>
        </div>
        <ul>
          {results.map((item, i) => (
            <li key={item.to + item.label} className={i === active ? "active" : ""}
                onMouseEnter={() => setActive(i)} onClick={() => go(item)}>
              <item.icon size={16} />
              <span>{item.label}</span>
              {item.hint && <span className="muted small">{item.hint}</span>}
            </li>
          ))}
          {results.length === 0 && <li className="muted">No matches</li>}
        </ul>
        <div className="palette-footer muted small"><kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> open</div>
      </div>
    </div>
  );
}
