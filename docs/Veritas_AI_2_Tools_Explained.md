# Veritas AI 2.0 — Tools Explained

**Installed:** 2026-10-30  
**Location:** Everything lives on **D:** (`D:\dev`) because C: is almost full.  
**Check everything works:** `python scripts\check_setup.py`

## 1. Programs installed on Windows

| Tool | Where | What it does |
|---|---|---|
| **Git** | Windows (small) | Version control: saves snapshots ("commits") of the code so you can go back in time and see changes. GitHub hosts them online and serves as the portfolio. |
| **Docker Desktop** | `D:\dev\tools\Docker` | Runs software in isolated **containers** (tiny pre-configured computers). One `docker compose up -d` starts the database, queue and automation, and the project runs the same on any machine. Redis has no official Windows version, so it runs in Docker. |
| **Ollama** | `D:\dev\tools\Ollama` | Runs AI language models (LLMs) **locally** on the GPU. It is free and offline, and documents never leave the computer, which matters for confidential invoices and contracts. |
| **qwen3:8b** | `D:\dev\cache\ollama\models` | The LLM itself (5.2 GB, 8 billion parameters). It fits in the RTX 3080's 10 GB of memory. Used in Phase 3 to turn document text into structured JSON. |

## 2. Services running in Docker

| Service | Port | What it does |
|---|---|---|
| **PostgreSQL** | 5432 | Main database: documents, extracted fields, verification results, human review decisions. |
| **pgvector** | (inside PostgreSQL) | Stores **vectors/embeddings** (lists of numbers representing meaning) and finds the texts closest in meaning to a question. This is the core of RAG (Phase 6). |
| **Redis** | 6379 | Very fast in-memory store used as a **job queue**. Slow work (OCR, AI) is queued so the website never freezes. |
| **n8n** | 5678 | Visual workflow automation in the browser (http://localhost:5678). Example: "contradiction found → notify reviewer → wait for approval" (Phase 9). |

## 3. Python libraries (inside `.venv`)

### Phase 1 — NLP basics
| Library | What it does |
|---|---|
| **NLTK** | Classic NLP toolkit: splits text into sentences and words (tokenization) and removes stopwords. |
| **regex** | Improved pattern matching. Extracts `PO-2026-0147`, dates, `$3,600.00`. |
| **textstat** | Readability scores, such as how hard a text is to read. |

### Phase 2 — Reading documents
| Library | What it does |
|---|---|
| **PyMuPDF** | Reads digital PDFs fast: text, positions, images. |
| **PaddleOCR** + **PaddlePaddle** | **OCR**: reads text from scanned images and photos. It finds text regions, then recognizes characters. PaddlePaddle is its engine. |
| **python-docx** | Reads Word `.docx` files. |
| **Pillow** | Basic image handling: open, resize, convert. |

### Phase 3 — Structured extraction
| Library | What it does |
|---|---|
| **spaCy** + **en_core_web_sm** | Industrial NLP with **Named Entity Recognition**. It recognizes organizations, dates and amounts. `en_core_web_sm` is the small English model. |
| **ollama** (Python) | Lets Python send prompts to the qwen3 model. |
| **Pydantic** | **Data validation**: defines the expected shape (`total: float`) and rejects bad LLM output. |

### Phases 5–6 — Verification and RAG
| Library | What it does |
|---|---|
| **PyTorch** (CUDA build) | Deep-learning engine that runs neural networks on the RTX 3080 GPU, often 10–50× faster than the CPU. The biggest download (2.7 GB). |
| **Transformers** (Hugging Face) | Downloads and runs pre-trained models, including **NLI** (Natural Language Inference) models that label sentence pairs as *entailment / contradiction / neutral*. These match Supported / Contradicted / Insufficient Evidence. |
| **Sentence Transformers** | Turns sentences into embeddings so "total amount due" and "invoice sum" end up close together. |
| **pgvector** (Python) | Lets Python use pgvector columns. |

### Phase 7 — Backend
| Library | What it does |
|---|---|
| **FastAPI** | Builds the **REST API** the frontend calls (e.g. `POST /documents`). It generates interactive docs automatically. |
| **Uvicorn** | The web server that runs the FastAPI app. |
| **python-multipart** | Lets FastAPI receive uploaded files. |
| **SQLAlchemy** | **ORM**: work with database rows as Python objects (`invoice.total`) without writing raw SQL. |
| **psycopg** | Driver SQLAlchemy uses to talk to PostgreSQL. |
| **redis** + **RQ** | Connects to Redis. RQ queues slow jobs and runs them in a separate **worker** process. Note: the RQ worker can't run on Windows, so it will run in Docker. |
| **httpx** | Makes HTTP requests from Python (e.g. calling n8n webhooks). |
| **python-dotenv** | Loads settings and secrets from `.env` so they stay out of the code. |

### Phase 10 — Testing and evaluation
| Library | What it does |
|---|---|
| **pytest** | Runs automated tests. |
| **scikit-learn** | ML tools, used here mainly for **evaluation**: precision, recall, F1-score. |

### Frontend (installed in Phase 8, inside `frontend/node_modules`)
| Library | What it does |
|---|---|
| **React** | Builds the UI from reusable components that re-render when their data changes. |
| **React Router** | Gives each page its own URL (`/documents/2`), so links (e.g. from n8n) open the right page. |
| **Axios** | Makes HTTP requests from the browser to the FastAPI backend. |
| **Vite** | Dev server with instant reload, and the production build tool (`npm run build`). |

The npm download cache is at `D:\dev\cache\npm` (user variable `npm_config_cache`).

## 3b. AI models downloaded during the build (all in `D:\dev\cache`)

| Model | Size | Used for |
|---|---|---|
| **qwen3:8b** (Ollama) | 5.2 GB | Structured extraction (Phase 3) and RAG answers (Phase 6) |
| **PP-OCRv5 mobile** detection + English recognition (PaddleOCR) | ~20 MB | Reading scans (Phase 2): 3× faster on CPU than the default models |
| **all-MiniLM-L6-v2** (Sentence Transformers) | 90 MB | 384-number embeddings: matching line items (Phase 4) and RAG search (Phase 6) |
| **cross-encoder/nli-deberta-v3-base** | 740 MB | NLI: supported / contradicted / neutral (Phases 5–6), chosen by measurement |
| **en_core_web_sm** (spaCy) | 13 MB | Named Entity Recognition for organisation names (Phase 3 rules) |

## 3c. Other tools used

| Tool | Role |
|---|---|
| **nginx** | Web server inside the frontend Docker image: serves the React files, forwards `/api` to the backend |
| **GitHub Actions** | Runs the tests automatically on GitHub's servers on every push (`.github/workflows/ci.yml`) |
| **Microsoft Edge (headless)** | Took the dashboard screenshots without opening a window |

## 4. Project files

| File / folder | Purpose |
|---|---|
| `.venv\` | The project's private Python environment |
| `requirements.txt` | List of libraries: `pip install -r requirements.txt` reinstalls them |
| `docker-compose.yml` | Defines the PostgreSQL, Redis and n8n containers |
| `.env` | Real settings and the generated database password. **Never upload to GitHub.** |
| `.env.example` | Safe template of `.env` to share |
| `scripts\check_setup.py` | Tests that every tool works |
| `phase1_nlp\text_analysis.py` | Phase 1 deliverable |
| `data\samples\` | Sample purchase order and invoice (with a deliberate mismatch) |

## 5. Where downloads are stored (D: drive)

| Folder | Contents |
|---|---|
| `D:\dev\veritas-ai` | The project |
| `D:\dev\cache` | pip, Hugging Face, PyTorch, PaddleOCR, NLTK, Ollama models, temp files |
| `D:\dev\tools` | Ollama, Docker Desktop |
| `D:\dev\docker-data` | Container images and database data |

Windows user environment variables (`TEMP`, `TMP`, `PIP_CACHE_DIR`, `HF_HOME`, `TORCH_HOME`, `PADDLE_PDX_CACHE_HOME`, `NLTK_DATA`, `OLLAMA_MODELS`) point to `D:\dev\cache`, so future downloads also go to D:.

## 6. Daily use

```powershell
cd D:\dev\veritas-ai
.\.venv\Scripts\Activate.ps1      # activate the Python environment
docker compose up -d              # start PostgreSQL, Redis, n8n (open Docker Desktop first)
python scripts\check_setup.py     # verify everything
```

`ollama launch claude` opens a separate Claude Code powered by the local qwen3:8b model. It's free and offline but weaker at coding. The project doesn't need it.

## 7. How it all connects

```text
Upload (React) -> FastAPI -> Redis/RQ queue
  -> PyMuPDF / PaddleOCR read the text
  -> NLTK + regex + spaCy find facts -> qwen3 (Ollama) + Pydantic make clean JSON
  -> PostgreSQL stores it; Sentence Transformers + pgvector index it
  -> Transformers NLI model + rules check for contradictions
  -> n8n notifies a reviewer -> result shown on the dashboard
```
