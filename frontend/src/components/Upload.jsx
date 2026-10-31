import { useRef, useState } from "react";
import { errorMessage, uploadDocuments } from "../api.js";
import { IconUpload } from "../icons.jsx";
import { can, useUser } from "../user.js";
import { useToast } from "../toast.jsx";

const ACCEPT = ".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";

export default function Upload({ onUploaded }) {
  const input = useRef(null);
  const user = useUser();
  const toast = useToast();
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(null); // null = idle, 0..1 = uploading
  const [names, setNames] = useState([]);

  async function send(files) {
    if (!files.length || progress !== null) return;
    setNames(files.map((f) => f.name));
    setProgress(0);
    try {
      const docs = await uploadDocuments(files, setProgress);
      toast(`${docs.length} document${docs.length > 1 ? "s" : ""} uploaded. Processing has started.`, { tone: "ok" });
      onUploaded?.(docs);
    } catch (err) {
      toast(errorMessage(err), { tone: "critical" });
    } finally {
      setProgress(null);
      input.current.value = "";
    }
  }

  if (!can(user, "reviewer")) return null; // viewers cannot upload
  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""} ${progress !== null ? "busy" : ""}`}
      onClick={() => input.current.click()}
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
          </>
        ) : (
          <>
            <strong>Uploading {names.join(", ")}</strong>
            <div className="progress"><span style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          </>
        )}
      </div>
    </div>
  );
}
