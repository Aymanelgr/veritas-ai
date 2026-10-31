# Veritas AI 2.0 — Build Log & Learning Notes

A record of everything built: what each file does, the concepts behind it,
and the problems we hit and how we solved them. All 10 phases are complete.

Related notes: `Veritas_AI_2_Project_Notes.md` (the plan),
`Veritas_AI_2_Tools_Explained.md` (every installed tool) and `README.md` (project overview).

---

## Project map (what each file is for)

```text
D:\dev\veritas-ai\
├── README.md                          project front page for GitHub
├── Veritas_AI_2_Project_Notes.md      the plan: features, architecture, roadmap
├── Veritas_AI_2_Tools_Explained.md    every installed tool and its job
├── Veritas_AI_2_Build_Log.md          this file
│
├── data\
│   ├── samples\                       one PO + one invoice in many formats (txt, pdf, docx, scans)
│   ├── synthetic\dataset.json         362 generated documents with known answers (Phase 4)
│   └── eval\                          hand-labelled NLI claims and RAG questions (Phases 5-6)
│
├── phase1_nlp\text_analysis.py        statistics, top words, regex facts, readability
├── phase2_documents\
│   ├── make_samples.py                generates PDF/DOCX/scan test files from the .txt files
│   └── reader.py                      read_document(path) -> text, for any format (OCR fallback)
├── phase3_extraction\
│   ├── schemas.py                     Pydantic models: ExtractedDocument, LineItem, Extraction
│   ├── parsing.py                     text -> dates / amounts helpers
│   ├── rules.py                       regex + spaCy extractor (no AI)
│   ├── llm.py                         wrapper around Ollama (qwen3:8b)
│   └── extractor.py                   LLM extraction + merge with rules + grounding
├── phase4_matching\
│   ├── synthetic.py                   generates the synthetic dataset
│   ├── matcher.py                     links invoices to purchase orders
│   └── evaluate.py                    precision / recall / F1 of matching
├── phase5_verification\
│   ├── models.py                      Finding, Evidence, DocumentRecord
│   ├── nli.py                         Natural Language Inference (claim vs passages)
│   ├── engine.py                      arithmetic + cross-document checks + explanations
│   └── evaluate.py                    rule F1 + NLI accuracy
├── phase6_rag\
│   ├── rag.py                         chunk, embed, search, answer with citations, check citations
│   └── evaluate.py                    retrieval / answer / refusal / citation metrics
├── db\
│   ├── models.py                      database tables (documents, chunks, links, findings, notifications)
│   └── session.py                     database connection + table creation
├── backend\
│   ├── main.py                        FastAPI REST API (all endpoints)
│   ├── schemas.py                     API request/response shapes
│   ├── jobs.py                        Redis queue
│   ├── pipeline.py                    the processing job: read -> ... -> verify -> notify
│   └── worker.py                      background worker (Windows-compatible)
├── frontend\                          React dashboard (Vite); see Phase 8
├── automation\n8n\                    n8n workflow templates (Phase 9)
├── tests\                             pytest suite; conftest.py isolates the test database
├── scripts\
│   ├── check_setup.py                 checks every tool/service
│   ├── setup_n8n.py                   installs + activates the n8n workflows
│   └── start_dev.ps1                  starts everything for development
├── docs\dashboard.png                 screenshot for the README
│
├── Dockerfile, frontend\Dockerfile    container images (Phase 10)
├── docker-compose.yml                 infrastructure + optional "app" profile
├── .github\workflows\ci.yml           automatic tests on GitHub
├── requirements.txt, pyproject.toml   Python dependencies, pytest settings
└── .env / .env.example, .gitignore, .gitattributes, .dockerignore
```

The `__init__.py` files (empty) mark folders as **packages**, so code can do
`from phase1_nlp.text_analysis import analyze`.

---

## Environment setup (done once)

| What we did | Why |
|---|---|
| Moved the project from OneDrive (C:) to `D:\dev\veritas-ai` | C: had only ~2 GB free; the stack needs ~15–25 GB. OneDrive would also try to sync thousands of library files. |
| Created `.venv` (virtual environment) | A private Python for this project: libraries don't clash with other projects, and `requirements.txt` can rebuild it anywhere. |
| Set `TEMP`, `PIP_CACHE_DIR`, `HF_HOME`, `NLTK_DATA`, `OLLAMA_MODELS`… to `D:\dev\cache` | Every tool downloads somewhere; these variables make sure it's D:, not C:. |
| Installed PyTorch from the **CUDA 12.8** index | The normal PyTorch build is CPU-only. The CUDA build uses the RTX 3080 GPU. |
| Docker Compose for PostgreSQL, Redis, n8n | Each runs in an isolated container, started with one command. |
| Pulled `qwen3:8b` with Ollama | The local LLM used from Phase 3 onwards. |

### Problems hit during setup
| Problem | Cause | Fix |
|---|---|---|
| `No space left on device` installing PyTorch | pip unpacks the 2.7 GB file in Windows' TEMP folder, which was on the full C: drive | Pointed TEMP/TMP to `D:\dev\cache\tmp` |
| `docker-credential-desktop not found` | The shell started before Docker's folder was added to PATH | Added `D:\dev\tools\Docker\resources\bin` to PATH. New terminals have it automatically. |
| Ollama would have saved models on C: | Ollama started before `OLLAMA_MODELS` was set | Restarted Ollama after setting the variable |

**Lesson:** environment problems (disk, PATH, environment variables) cause more
failures than code does. Read the *exact* error message, because it usually names the cause.

---

## Phase 1 — NLP Fundamentals ✅

**Deliverable:** `phase1_nlp/text_analysis.py`  
**Run:** `python phase1_nlp\text_analysis.py data\samples\invoice.txt` (add `--json` for JSON)

### What it does, step by step
1. **Tokenization (NLTK):** `sent_tokenize` splits text into sentences and
   `word_tokenize` into words. Almost every NLP pipeline starts here.
2. **Stopword removal + counting:** drops "the", "and"… and counts the remaining
   words with `Counter`. The top words ("invoice", "total", "due") hint at the document type.
3. **Regex fact extraction:** patterns describe the *shape* of a fact:
   - `\b(?:PO|INV)-\d{4}-\d{3,}\b`: PO-2026-0147
   - `[$€£]\s?\d+(?:,\d{3})*(?:\.\d{2})?`: $1,250.00
   - three date formats: 2026-10-01, 11/17/2026, October 20, 2026
4. **Readability (textstat):** the Flesch score is based on sentence and word
   length. It's designed for prose, so it's only approximate on tables.

### Key insight
The invoice contains `PO-2026-0147`, the same reference as the purchase order.
That single extracted fact is how Phase 4 will link the two documents.

---

## Phase 2 — OCR & Document Processing ✅

**Deliverable:** `phase2_documents/reader.py`, a document-reading pipeline  
**Run:** `python -m phase2_documents.reader data\samples\invoice_scan.png`  
**Test:** `python -m pytest`

### The problem it solves
Documents arrive in many formats, but every later phase needs **plain text**.
`read_document(path)` is the single entry point that hides the differences:

| Format | How it's read | Method label |
|---|---|---|
| `.txt` | read the file directly | `text` |
| `.docx` | **python-docx**: paragraphs and tables, in document order | `docx` |
| `.pdf` with text | **PyMuPDF**: reads the PDF's hidden text layer (instant, exact) | `pdf-text` |
| `.pdf` scanned | extracts the page image, then **PaddleOCR** | `ocr` |
| `.png`, `.jpg`… | **PaddleOCR** | `ocr` |

### Concepts

**Digital PDF vs scanned PDF.** A digital PDF (exported from Word, say) stores
the actual characters, so the computer can read them exactly. A scanned PDF is just a
*photo* wrapped in a PDF: the computer sees pixels, not letters. The reader
checks each page: if it has fewer than 20 characters of text, it's treated as
a scan and sent to OCR. This works per page, so mixed documents work too.

**OCR (Optical Character Recognition)** works in two stages:
1. **Detection:** find *where* text is (draws boxes around text regions).
2. **Recognition:** read *what* each box says, with a confidence score (0–1).

We use the PP-OCRv5 "mobile" models: 3× faster on CPU than the default ones
(13 s vs 45 s per page) with equal accuracy on our documents.

**Reading order and deskewing.** OCR returns separate boxes ("Item", "Qty",
"Unit Price"), not lines. On a tilted scan, boxes on the same line sit at
different heights; in our scan "Item" came *after* "Qty". `_group_into_lines`
fixes this:
1. Measure each box's tilt from its top edge (`atan2`), and take the median.
2. Rotate every box centre by the opposite angle, so lines become horizontal.
3. Sort boxes top to bottom and start a new line when a box is more than half a
   line-height below the line's first box.
4. Sort each line left to right and join.

**Confidence scores.** Each page stores how it was read and the mean OCR
confidence. Later phases can say "this total came from OCR at 0.99 confidence"
and treat low-confidence text with suspicion. This follows the principle
*preserve source evidence*.

**Pydantic models.** `Page` and `DocumentText` define the exact shape of the
output (`method` can only be one of four values). `--json` uses
`model_dump_json()`. FastAPI (Phase 7) uses the same models directly.

**Lazy loading with `@cache`.** Loading PaddleOCR takes seconds. `_ocr_engine()`
creates it only the first time OCR is needed and reuses it after that. Reading a
`.txt` never loads it at all.

### Problems hit in Phase 2
| Problem | Cause | Fix |
|---|---|---|
| `NotImplementedError: ConvertPirAttribute2RuntimeAttribute…` | Known bug in PaddlePaddle 3.3's **oneDNN** (an Intel CPU accelerator) on Windows | `enable_mkldnn=False` |
| OCR slow (45 s/page) | Default "medium" models are heavy for CPU | Switched to "mobile" models (13 s, same accuracy) |
| Scanned **PDF** read `11/17/2026` as `1l/17/2026`, but the PNG was fine | The code re-rendered the 150 DPI image at 200 DPI. The resampling blurred it slightly, and OCR confused **1** with **l** | Extract the embedded image at its original resolution (`_page_image`) |

**Lessons:**
- OCR confuses look-alike characters: 1/l/I, 0/O, 5/S. Image quality matters.
- That bug was found only because a test compared OCR output against known
  correct text. *Evaluate AI rather than assuming correctness.*
- In Phase 3, validation (e.g. "a date must contain only digits") adds a second
  safety net.

### The tests (`tests/test_reader.py`)
| Test | What it proves |
|---|---|
| `test_txt` | Plain text is read as-is |
| `test_docx_keeps_table_rows_in_order` | Word tables come out row by row, in the right place |
| `test_digital_pdf_uses_text_layer_not_ocr` | Digital PDFs skip slow OCR |
| `test_unsupported_type` | Unknown formats fail clearly, not silently |
| `test_group_into_lines_undoes_tilt` | Deskewing works on a synthetic tilted, shuffled layout (no OCR model needed) |
| `test_ocr_finds_same_facts_as_original` ×2 | **End to end:** OCR on the PNG and the scanned PDF, then the Phase 1 analyzer must find *exactly* the same references, dates, amounts and emails as on the clean `.txt` |

`pyproject.toml` tells pytest to look in `tests/` and to allow imports from
the project root.

---

## Phase 3 — Structured Extraction ✅

**Deliverable:** `phase3_extraction/`: text in, validated JSON out  
**Run:** `python -m phase3_extraction.extractor data\samples\invoice_scan.png` (add `--rules` for no LLM)

### What it produces
An `ExtractedDocument`: type, number, references to other documents, dates,
buyer, supplier, currency, line items (description, quantity, unit price,
total), subtotal, tax, total, payment terms. It's wrapped in an `Extraction`
that also records **how** the data was obtained and **where** each value came from.

### Concepts

**Two extractors, combined (hybrid).**
- `rules.py`: regex patterns + spaCy NER (Named Entity Recognition: spaCy
  labels "Atlas Manufacturing SARL" as an ORG). Fast and predictable, but only
  works on layouts it was written for.
- `extractor.py`: the LLM (qwen3:8b) reads the whole document and fills the
  schema. It understands varied layouts, but it can skip fields or make things up.
- `merge()`: start from the LLM answer and fill any field it left empty with
  the rule value, recording which fields were filled (`filled_by_rules`). The
  dashboard shows these as "(rules)".

**Structured outputs.** `llm.chat(..., schema=ExtractedDocument)` passes the
Pydantic model's JSON schema to Ollama, which *constrains* the model so it can
only produce JSON of that shape. Pydantic then validates it: wrong types are
rejected, and the error is sent back to the model for one retry.

**Settings for reliable extraction:** `temperature=0` (always pick the most
likely word, so results are repeatable) and `think=False` (qwen3's
"reasoning" mode is slow and not needed for copying values).

**Decimal, not float, for money.** `0.1 + 0.2 = 0.30000000000000004` in
floating point. `Decimal` stores 0.10 exactly, which matters when comparing totals.

**Grounding (anti-hallucination).** `ground()` searches the source text for
every extracted value. If it's found, the line is stored as **evidence**
(`evidence["total"] = "Total Due: $5,100.00"`). If not, the value goes into
`ungrounded`, meaning the AI may have invented it. Numbers and dates are
compared as values, so `$1,250.00` matches `1250`.

### Problems and lessons
| Problem | Cause / lesson | Fix |
|---|---|---|
| First LLM run returned no line items, buyer or subtotal | Happened once, on the model's cold start; the next 8 runs were identical and complete. *"Usually works" is not enough.* | Hybrid merge with the rule extractor |
| LLM never fills `delivery_date` ("shipped on October 17") | The model doesn't treat "shipped" as delivery | Rules fill it |
| Evidence for "gloves quantity = 20" pointed to "Delivery … October **20**" | Grounding took the first line containing 20 (found in Phase 5) | Line-item values are searched in their own row first |

**Measured:** the LLM matches the hand-written gold answer on every field, with
zero ungrounded values (`tests/test_extraction.py`).

---

## Phase 4 — Document Matching ✅

**Deliverable:** `phase4_matching/matcher.py`: decides which documents belong together  
**Run:** `python -m phase4_matching.evaluate` (add `--seed 99` for a fresh dataset)

### Why synthetic data
Two sample documents can't show whether matching works in general. `synthetic.py`
generates 362 documents **with known answers** and deliberate difficulties:
missing PO references (30%), supplier name variants ("NORDLINE IND. SUPPLIES"),
reworded items ("HP-200 Hydraulic Pump"), shuffled rows, *distractor* POs from the
same supplier, *orphan* invoices with no PO, plus 66 injected discrepancies for Phase 5.

### How matching works
1. **Explicit reference.** The invoice cites a known PO number → linked (score 1.0).
2. **Fuzzy score** when there's no reference:
   - **Names:** normalize (lowercase, drop punctuation and "Ltd/SARL/Inc"), then
     `SequenceMatcher` string similarity; a prefix counts as a match ("Kestrel Office").
   - **Line items:** each description becomes an **embedding** (384 numbers from
     `all-MiniLM-L6-v2`). Similar meaning → nearby vectors, measured with **cosine
     similarity** (the dot product of unit vectors). `align_items` pairs the most
     similar items greedily, above 0.6.
   - **Dates:** the invoice must come after the PO, within 120 days.
   - Weighted sum: items 50%, supplier 25%, buyer 15%, dates 10%; the threshold is 0.8.
3. **Hard constraints:** a different supplier or buyer, or an invoice dated before
   the PO, means *no link*, whatever the other signals say.
4. **One-to-one:** best scores first; each invoice and each PO is used once.

### Evaluation vocabulary
- **Precision:** of the links we made, how many are right? (Wrong links are dangerous:
  they would cause false contradictions.)
- **Recall:** of the true links, how many did we find?
- **F1:** the harmonic mean; it's only high when both are high.
- **Overfitting:** tuning a system until it fits one dataset rather than the
  problem. The guard is to evaluate on **held-out** data it has never seen (other seeds).

### Results and the journey there
| Version | Precision | Recall | What happened |
|---|---|---|---|
| References only | 1.00 | 0.69 | Safe but misses every invoice without a PO number |
| + fuzzy (first try) | 0.955 | 1.00 | 7 wrong links: orphans attached to distractors |
| + hard constraints, threshold 0.8 | **1.00** | **1.00** | Also 1.00/1.00 on two unseen seeds; 4× faster, because gates skip the embedding work |

---

## Phase 5 — AI Verification ✅

**Deliverable:** `phase5_verification/`: the contradiction-detection and evidence-verification engine  
**Run:** `python -m phase5_verification.engine data\samples\invoice.txt data\samples\purchase_order.txt`

### Every finding contains
A **claim** in plain English, a **verdict** (supported / contradicted /
insufficient_evidence), a **severity** (info / warning / critical), an
**explanation**, and **evidence** (document, field, value, source line).

### The checks
- **Inside one document:** quantity × unit price = line total; the lines add up
  to the subtotal; subtotal + tax = total (with 1 cent of rounding tolerance).
  A missing tax amount gives *insufficient evidence*, never a guess.
- **Invoice vs PO** (only for linked documents): line items aligned with the
  Phase 4 embeddings; quantity and unit price compared; invoiced items not on
  the order → *contradicted*; ordered items not invoiced → *info* (they may be
  invoiced separately); invoice after the order; shipped before the deadline.
- **Is the difference explained?** A quantity or price change is only a
  problem if nothing approves it. NLI searches every line of both documents for
  "The buyer approved a change to the order." If it's found, the severity drops
  to *warning* and the explanation quotes the line. If not, it stays *critical*.

### NLI (Natural Language Inference)
A **cross-encoder** model reads a (premise, hypothesis) pair *together* and
outputs three probabilities: entailment, contradiction, neutral. These map
directly to supported, contradicted and insufficient evidence.

### The obligation trap
Small NLI models read *"Any change **must be** approved in writing"* (a rule) as
*"a change **was** approved"* (a fact), with 0.95 confidence. If left in, every PO
would explain its own discrepancies. Rewording the claim made the model miss
real approvals instead. **Fix:** a regex removes obligation sentences (must,
shall, should, required…) before NLI sees them.

**Asymmetric cost:** a *missed* approval only sends the case to a human (safe).
A *false* approval would hide a real problem (dangerous). The design always
fails toward human review.

### Choosing the model by measurement
24 hand-labelled claims (`data/eval/nli_claims.json`), including traps:

| Model | Accuracy | Precision on "supported" |
|---|---|---|
| nli-deberta-v3-small | 83% | 100% (fails "24 months = 2 years") |
| **nli-deberta-v3-base** | **92%** | **100%** ← chosen |
| nli-roberta-base | 83% | 100% (thinks "due 11/17" ≠ "November") |

The rules on 66 injected discrepancies: **precision, recall and F1 = 1.00**, and
no false alarms on clean invoices (`classification_report` from scikit-learn).

---

## Phase 6 — RAG (Retrieval-Augmented Generation) ✅

**Deliverable:** `phase6_rag/rag.py`: question answering with citations  
**Run:** `python -m phase6_rag.rag ask "When is the invoice payment due?"`

### The pipeline
1. **Chunking:** consecutive lines are grouped into passages (≤300 characters;
   a blank line ends a chunk).
2. **Contextual embeddings:** each chunk is embedded *with* its document
   identity ("purchase order PO-2026-0147: Total: $3,600.00"), because a bare
   "Total: $3,600" could belong to any document.
3. **Storage:** PostgreSQL table `chunks` with a `vector(384)` column (pgvector).
4. **Hybrid search:** pgvector orders chunks by **cosine distance** to the
   question's embedding (meaning), **plus** an exact-text search for IDs like
   `PO-2026-0147` (embeddings are weak at exact codes).
5. **Generation:** qwen3 receives numbered sources and must answer *only* from
   them, cite [n] after every sentence, and reply "The documents do not contain
   this information." when the answer isn't there.
6. **Citation checking:** the answer is split into clauses at each citation, and
   NLI checks every clause against **its own** cited source.

### Problems and fixes in citation checking
| Problem | Fix |
|---|---|
| "2 ordered [2], and 3 invoiced [1]" holds two claims from two sources | Split at citation markers; check each clause separately |
| One unrelated line ("Invoice Date: 2026-10-18") made a correct sentence look "contradicted" | A citation is either *supported* or *not backed by its source*, never "contradicted" |
| NLI can't read table rows (`Hydraulic pump HP-200   2   $1,250.00`) | **Table linearization:** "Item: Hydraulic pump HP-200, Qty: 2, …" |
| "According to the purchase order…" was judged neutral, because the row doesn't say where it's from | Each premise is prefixed with "In purchase order PO-2026-0147:" |

### Results (`python -m phase6_rag.evaluate`, 11 questions)
Retrieval 9/9 · correct answers 9/9 · correct refusals 2/2 · citation accuracy 94%.
The remaining miss is an OCR chunk whose table header is in a different chunk.

The evaluation and the tests use a **separate database** (`veritas_test`),
which is reset on every run, so experiments never touch real data.

---

## Phase 7 — Backend (FastAPI + Redis/RQ) ✅

**Deliverable:** `backend/`: the REST API and background processing  
**Run:** `uvicorn backend.main:app --port 8000` and, in a second terminal, `python -m backend.worker`
→ interactive docs at http://localhost:8000/docs

### Concepts
- **REST API:** URLs + HTTP methods (`GET` reads, `POST` creates or acts,
  `DELETE` removes) that exchange JSON. FastAPI validates every request with
  Pydantic (`schemas.py`) and generates documentation automatically.
- **ORM (SQLAlchemy):** tables are Python classes (`db/models.py`), rows are
  objects. `JSONB` columns store flexible data (the extraction, the evidence).
- **Dependency injection:** `Depends(db)` gives each request its own database
  session and always closes it.
- **Background jobs:** processing takes 10–40 s, so the upload answers
  **202 Accepted** immediately and puts a job on the Redis queue. The **worker**
  runs `pipeline.process_document`: read → extract → index → re-match →
  verify → save findings → notify n8n. The dashboard polls the status.
- **Human reviews survive reprocessing:** only `pending` / `not_required`
  findings are replaced.

### Endpoints
| Method + URL | Purpose |
|---|---|
| `POST /api/documents` | upload one or more files |
| `GET /api/documents`, `GET /api/documents/{id}` | list; detail with text, extraction, links, findings |
| `GET /api/documents/{id}/file` | the original file (shown inline) |
| `POST /api/documents/{id}/reprocess`, `DELETE /api/documents/{id}` | redo / remove |
| `GET /api/findings`, `POST /api/findings/{id}/review` | review queue; confirm or dismiss |
| `POST /api/ask` | RAG question |
| `GET/POST /api/notifications` | n8n inbox (POST needs the token) |
| `GET /api/stats`, `GET /api/health` | dashboard numbers; service status |

### Problems and fixes
| Problem | Cause | Fix |
|---|---|---|
| RQ's default worker can't run on Windows | It uses `fork()` (Linux/Mac only) and `SIGALRM` timeouts | `SimpleWorker` + `TimerDeathPenalty`. A bonus: the AI models stay loaded between jobs |
| Invoices never linked in the database | Documents are keyed by id (1, 2…), but invoices cite numbers ("PO-2026-0147") | The matcher resolves references by document number |
| The status still said "processed" right after Reprocess | Queuing didn't change the status (a race condition) | Set the status to "uploaded" before queuing |

---

## Phase 8 — Frontend (React dashboard) ✅

**Deliverable:** `frontend/`: the web interface  
**Run:** `cd frontend; npm run dev` → http://localhost:5173

### Structure
| File | Role |
|---|---|
| `src/api.js` | every backend call (Axios) in one place |
| `src/usePolling.js` | a custom React **hook**: load data, then reload every 3 s while something is processing |
| `src/App.jsx` | layout + **routes** (React Router): `/`, `/documents`, `/documents/:id`, `/reviews`, `/ask` |
| `src/pages/*.jsx` | one component per page |
| `src/components/` | reusable pieces: `Badge`, `Upload` (drag & drop), `FindingCard` (evidence + review buttons), `Inbox` |
| `vite.config.js` | dev server + **proxy**: `/api` calls are forwarded to FastAPI |

### React concepts used
**Components** (functions returning UI), **props** (inputs to a component),
**state** (`useState`: data that re-renders the UI when it changes), **effects**
(`useEffect`: side effects like timers), `useCallback` (keeps a function
identical between renders so effects don't re-run endlessly).

### Problems and fixes
| Problem | Cause | Fix |
|---|---|---|
| Proxy error `ECONNREFUSED` | Node resolves `localhost` to IPv6 `::1`; Uvicorn listens on IPv4 | Proxy to `127.0.0.1:8000` |
| The PDF viewer would download the file instead of showing it | `FileResponse(filename=…)` sends `Content-Disposition: attachment` | `content_disposition_type="inline"` |
| The link reason said "invoice cites 1" | The database id was shown instead of the PO number | Show the number; refresh the reasons of existing links |

Screenshots were taken with **headless Microsoft Edge** (`msedge --headless
--screenshot`), because Chrome isn't installed and C: has no room for it.

---

## Phase 9 — Automation (n8n) ✅

**Deliverable:** `automation/n8n/`: two workflows, installed by `python scripts\setup_n8n.py`  
**See them:** http://localhost:5678

### The workflows
1. **Notify reviewer:** `Webhook` (the worker POSTs findings to
   `/webhook/veritas-review`) → `Code` (formats a title and message in
   JavaScript) → `HTTP Request` (posts it to the Veritas inbox) + `Email` (disabled
   until you add SMTP credentials in n8n).
2. **Daily reminder:** `Schedule` (every day at 9:00) or `Manual trigger` →
   `HTTP Request` (gets pending findings) → `Code` (summarizes; stops if there's
   nothing pending) → `HTTP Request` (inbox).

### Concepts
- **Webhook:** a URL that starts a workflow when something POSTs to it
  ("don't call us, we'll call you").
- **Shared-secret token:** n8n sends `X-Veritas-Token`, and the API rejects
  anything else with **401**. `secrets.compare_digest` compares in constant time,
  so the token can't be guessed character by character from response times.
- **Secrets stay out of Git:** the workflow files contain `__AUTOMATION_TOKEN__`;
  `setup_n8n.py` fills in the real value from `.env` at install time.
- **Container networking:** inside n8n, `localhost` is n8n itself; the host PC is
  `host.docker.internal`, and other containers are reached by service name (`api`, `n8n`).

### Problems and fixes
| Problem | Cause | Fix |
|---|---|---|
| `SQLITE_BUSY: database is locked` on import | n8n's SQLite database allows one writer, and the server held it | Stop n8n, run the CLI in a one-off container on the same volume, start again |
| `Cannot POST /webhook/...` | The test arrived before n8n finished loading the workflows | Wait for start-up |
| The reminder couldn't run from the CLI | A schedule trigger can't be started manually | Add a Manual Trigger node (it also enables the editor's "Test" button) |
| Tests would post into the real inbox | `.env` contains the real webhook URL | `conftest.py` blanks `N8N_WEBHOOK_URL` during tests |

---

## Phase 10 — Deployment, Testing, Documentation ✅

| File | Role |
|---|---|
| `Dockerfile` | backend image: Python 3.12 + OpenCV libraries + CPU PyTorch + dependencies + code. The dependencies are copied **before** the code, so Docker's layer cache skips reinstalling them after a code change |
| `frontend/Dockerfile` | **multi-stage build**: Node builds the static files, then only those are copied into a small nginx image |
| `frontend/nginx.conf` | serves the app, forwards `/api/` to the `api` container, and sends unknown paths to `index.html` (so React Router URLs work on reload) |
| `docker-compose.yml` | `docker compose up -d` = infrastructure for development; `--profile app` adds api + worker + frontend (http://localhost:8080). The API and worker share an `uploads` volume |
| `.dockerignore` | keeps `.env`, `.venv`, `.git` and test data out of images |
| `.github/workflows/ci.yml` | **Continuous Integration:** on every push, GitHub starts Postgres + Redis, installs everything and runs pytest, and builds the frontend |
| `scripts/start_dev.ps1` | one command to start the whole development setup |
| `README.md` | the project's front page: features, measured results, architecture, how to run |

### Docker verification
`docker compose --profile app build` produced `veritas-ai-api` / `veritas-ai-worker`
(4.75 GB: one image used two ways, stored once) and `veritas-ai-frontend` (74 MB thanks
to the multi-stage build). With `--profile app up -d`, a test invoice uploaded at
http://localhost:8080 was read, extracted by the LLM (Ollama reached through
`host.docker.internal`) and verified entirely inside containers. The test invoice
contained an accidental typo (total $514 instead of $504), and Veritas flagged it as a
critical arithmetic contradiction.

**Problem hit:** the first build was killed when the PC ran low on memory. Docker's
layer cache meant the rebuild reused every finished step and completed in seconds.
**Lesson:** order the Dockerfile from rarely-changing steps (system packages,
dependencies) to often-changing ones (your code).

### The test suite
`python -m pytest`: unit tests (parsing, grouping, chunking), integration tests
(database, OCR, LLM), and an **end-to-end** API test of the whole MVP: upload PO
+ scanned invoice → linked → pump issue found with evidence → human confirms
→ statistics update. Tests skip themselves when Ollama or PostgreSQL is missing.

---

## Final polish ✨

| Change | Why / how |
|---|---|
| **Visual redesign** | Design tokens (named colors in `:root`), cards with shadows, icon set (`src/icons.jsx`, inline SVG, so no extra library), logo (`public/favicon.svg`) |
| **Automatic dark mode** | `@media (prefers-color-scheme: dark)` redefines the tokens; follows the Windows theme |
| **Order vs invoice table** | New `comparison` field in `GET /api/documents/{id}`: the invoice's items aligned with the PO's (same `align_items` as verification), status match / mismatch / not invoiced / unexpected; mismatches highlighted in red |
| **Page previews** | `GET /api/documents/{id}/preview?page=N` renders a PDF page to PNG with PyMuPDF, so scans display in every browser (built-in PDF viewers don't work everywhere) |
| **Verdict banner, summary card** | The answer first ("1 critical issue needs review"), details after |
| **Service status in the sidebar** | Green or red dots for database, job queue and LLM (`/api/health` every 15 s), plus a pending-review counter |
| **Chat-style Q&A** | Question bubbles, citation chips, cited sources highlighted; `/ask?q=…` links ask immediately |
| **Formatting** | `src/format.js`: currency with `Intl.NumberFormat`, relative times ("6 h ago") |
| **README** | Logo, badges, screenshot gallery (`docs/`) |

**Lesson:** "pretty" is mostly *hierarchy*: show the verdict first, the evidence second and
the raw data last, and use color only to mean something (red = problem, green = OK).

### Smooth and interactive

| Feature | How it works |
|---|---|
| Page transitions, staggered lists | CSS `@keyframes`; each item gets `style="--i: n"` and `animation-delay: calc(var(--i) * 45ms)` |
| Numbers count up | `useCountUp` (`src/motion.js`): `requestAnimationFrame` + an ease-out curve |
| Smooth expand / collapse | Animating `grid-template-rows` from `0fr` to `1fr`, which reaches the content's natural height without measuring it |
| Toasts with Undo | `src/toast.jsx`: a React **context** lets any component call `useToast()`; Undo sends `decision: "pending"` to the API |
| Upload progress bar | Axios `onUploadProgress` |
| Ctrl+K command palette | `CommandPalette.jsx`: a global key listener, fuzzy filter, ↑/↓/Enter navigation |
| Keyboard review | `Reviews.jsx`: J/K move, C/D decide; the command is cleared right after delivery so the *next* card isn't decided by accident |
| Linked highlighting | Hovering a finding highlights its comparison row (and the other way round) through shared `focus` state |
| Lightbox, click-to-reveal source | Small components with Esc-to-close and `aria-expanded` |
| Word-by-word answers | `useReveal` shows tokens one by one; citation chips scroll to and flash their source |
| Themes | `useTheme` sets `<html data-theme>`, saved in `localStorage` (inside try/catch, since storage can be blocked) |
| Accessibility | `@media (prefers-reduced-motion)` disables animation; visible focus rings; rows open with Enter |

### Problems and fixes
| Problem | Cause | Fix |
|---|---|---|
| The whole app was blank | `useEffect(() => window.scrollTo(...))` *returned* `scrollTo`'s result, and newer browsers return a **Promise**. React expects an effect to return only a cleanup function | Braces: `useEffect(() => { window.scrollTo(...); })` |
| A keyboard decision could hit the next card too | The same command object reached the newly active card | Clear the command right after it's delivered |

**Testing interactions:** `scripts/ui_check.py` uses **Playwright** to drive the installed
Microsoft Edge (`channel="msedge"`, no browser download) through 17 checks. It found the blank-page
crash, which unit tests and screenshots had missed.

---

## Example documents, and what they taught us 🧪

`scripts/make_examples.py` writes `examples/`: 10 scenarios (19 documents) in mixed formats,
including scans with random tilt and grain. `examples/README.md` explains each one, and
`scripts/check_examples.py` runs them all through the real pipeline and compares the results
with `examples/expected.json`.

The first run gave **6/10**, and the failures exposed two real weaknesses in the app:

| Problem | Evidence | Fix |
|---|---|---|
| The LLM sometimes drops decimal points: `$18.50` → `1850`, `$178.40` → `178` | Grounding had already flagged these values as *ungrounded*, but they were still used, causing false "price mismatch" alarms | `repair()` in `extractor.py`: **never act on a value not found in the document**. It is replaced by the rule-based value if that one is grounded, otherwise emptied. The prompt also says "keep the decimal point" explicitly |
| OCR read a table row's quantity as missing and the next row's as "s 5" | Two identical "5"s stacked in the Qty column were **detected as one tall box** (59 px instead of ~24, confidence 0.47), misread, and placed on the wrong line | `_split_multiline_boxes()` in `reader.py`: a box about twice the normal line height is cut into one slice per line, and each slice is re-read by the recognition model alone (both "5"s then read at 100%) |

The first suspicion was the detector's confidence threshold. Measuring showed it made no
difference (same 26 boxes at 0.6, 0.5 and 0.4), which pointed to the real cause. **Lesson:**
realistic test data finds bugs that clean test data never will, and measuring before changing
things avoids "fixing" the wrong part.

After the fixes: **10/10 scenarios** behave as documented, with zero ungrounded values.

---

## How the MVP requirements are met

| MVP requirement (from the project notes) | Where |
|---|---|
| 1. Upload a purchase order and a scanned invoice | Dashboard drop zone → `POST /api/documents` |
| 2. Read both documents | Phase 2 reader (PyMuPDF / PaddleOCR) |
| 3. Extract their important information | Phase 3 (LLM + rules + grounding) |
| 4. Establish that they concern the same transaction | Phase 4 matcher (reference or fuzzy) |
| 5. Compare amounts, quantities and dates | Phase 5 rules |
| 6. Detect unexplained inconsistencies | Phase 5 + NLI approval search |
| 7. Display supporting evidence | Source lines in every finding card |
| 8. Trigger an n8n notification | Phase 9 workflow → inbox (email optional) |
| 9. Allow a human to review the result | Confirm / Dismiss in the dashboard |

---

## Try it yourself (exercises)

1. Open `invoice_scan.png` in Paint, scribble over part of the total, and upload
   it. What happens to the OCR confidence and the findings?
2. Add the line *"Pump quantity increased to 3, approved by the buyer by email
   on 2026-10-10."* to a copy of `invoice.txt` and upload it. The pump finding
   should drop from critical to warning, quoting your line.
3. Write an invoice with no PO number but the same supplier and items, and watch
   fuzzy matching link it.
4. In `phase4_matching/matcher.py`, set `LINK_THRESHOLD = 0.6` and rerun the
   evaluation. Explain what happens to precision and why.
5. Add 5 new claims to `data/eval/nli_claims.json` and rerun the Phase 5
   evaluation. Can you find a new weakness?
6. In n8n, add SMTP credentials and enable the email node, so you receive real emails.
