import { useRef, useState } from "react";
import { errorMessage, uploadDocuments } from "../api.js";
import { IconChevron, IconUpload } from "../icons.jsx";
import { can, useUser } from "../user.js";
import { useToast } from "../toast.jsx";

const ACCEPT = ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";
const AUTO = { doc_type: "auto", language: "auto", currency: "auto", day_first: "auto" };
const OPTIONS = [
  ["doc_type", "Document type", [["auto", "Detect"], ["invoice", "Invoice"], ["purchase_order", "Purchase order"],
    ["contract", "Contract"], ["other", "Other"]]],
  ["language", "Language", [["auto", "Detect"], ["en", "English"], ["fr", "French"], ["ar", "Arabic"]]],
  ["currency", "Currency", [["auto", "Detect"], ["MAD", "MAD (dirham)"], ["EUR", "EUR (euro)"], ["USD", "USD (US dollar)"]]],
  ["day_first", "Dates", [["auto", "Detect"], ["true", "Day first (31/12/2026)"], ["false", "Month first (12/31/2026)"]]],
];

// What Veritas can check depends on what was uploaded; saying so avoids false reassurance.
function WhatGetsChecked() {
  return (
    <div className="upload-help">
      <div>
        <strong>With an invoice alone</strong>
        <span>Line, subtotal, tax and total arithmetic; missing or unreadable fields; currency and date reading.</span>
      </div>
      <div>
        <strong>With its purchase order too</strong>
        <span>Ordered vs invoiced quantities and prices, units, unexpected or missing items, dates and delivery
          deadlines, and cumulative billing across partial invoices.</span>
      </div>
    </div>
  );
}

export default function Upload({ onUploaded }) {
  const input = useRef(null);
  const user = useUser();
  const toast = useToast();
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(null); // null = idle, 0..1 = uploading
  const [names, setNames] = useState([]);
  const [showOptions, setShowOptions] = useState(false);
  const [overrides, setOverrides] = useState(AUTO);
  const custom = Object.entries(overrides).filter(([, v]) => v !== "auto");

  async function send(files) {
    if (!files.length || progress !== null) return;
    setNames(files.map((f) => f.name));
    setProgress(0);
    try {
      const docs = await uploadDocuments(files, setProgress, overrides);
      toast(`${docs.length} document${docs.length > 1 ? "s" : ""} uploaded. Processing has started.`, { tone: "ok" });
      onUploaded?.(docs);
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setProgress(null);
      if (input.current) input.current.value = ""; // the page may have been left during the upload
    }
  }

  if (!can(user, "reviewer")) return null; // viewers cannot upload
  return (
    <div className="upload">
      <div
        className={`dropzone ${dragging ? "dragging" : ""} ${progress !== null ? "busy" : ""}`}
        role="button" tabIndex={0}
        onClick={() => input.current.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.current.click())}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          send([...e.dataTransfer.files]);
        }}
      >
        <input ref={input} type="file" multiple accept={ACCEPT} hidden
               onChange={(e) => send([...e.target.files])} />
        <span className="dropzone-icon"><IconUpload size={22} /></span>
        <div className="dropzone-text">
          {progress === null ? (
            <>
              <strong>{dragging ? "Release to upload" : "Drop documents here, or click to browse"}</strong>
              <span className="muted">Purchase orders, invoices and contracts: PDF, Word, text or scanned images</span>
              {custom.length > 0 && (
                <span className="muted small"> · Using your settings for {custom.map(([k]) => k.replace("_", " ")).join(", ")}</span>
              )}
            </>
          ) : (
            <>
              <strong>Uploading {names.join(", ")}</strong>
              <div className="progress"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
            </>
          )}
        </div>
      </div>
      <button className="link toggle" onClick={() => setShowOptions(!showOptions)} aria-expanded={showOptions}>
        <IconChevron size={14} className={`chevron ${showOptions ? "open" : ""}`} />
        Upload options and what gets checked
      </button>
      <div className={`collapse ${showOptions ? "open" : ""}`}>
        <div>
          <div className="upload-options">
            <p className="muted small">Leave on “Detect” unless Veritas guessed wrong. Your choices apply to the files
              you upload next, and can be changed later on each document.</p>
            <div className="option-grid">
              {OPTIONS.map(([key, label, choices]) => (
                <label key={key}>
                  <span>{label}</span>
                  <select value={overrides[key]} onChange={(e) => setOverrides({ ...overrides, [key]: e.target.value })}>
                    {choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <WhatGetsChecked />
          </div>
        </div>
      </div>
    </div>
  );
}
