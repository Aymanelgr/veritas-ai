# Veritas AI 2.0 — Project Notes

**Project:** Intelligent Document Processing, Verification & Automation Platform  
**Field:** AI Engineering, NLP, LLMs, OCR, RAG and Automation  
**Goal:** Build a portfolio-ready AI application while learning every technology step by step.

## 1. Project Idea

Veritas AI is an intelligent platform that automatically reads, understands, analyzes and compares documents.

It can detect potential inconsistencies, verify information using documentary evidence, answer questions and automate workflows.

**Example:** A company uploads a purchase order and an invoice. Veritas AI identifies that they concern the same transaction, compares amounts and quantities, flags unexplained differences and uses n8n to notify someone for review.

## 2. Main Features

- **Document upload:** PDF, DOCX, TXT and scanned images.
- **OCR:** Extract text from scanned documents.
- **NLP:** Process text, identify important information and analyze readability.
- **LLM:** Understand context and extract structured information.
- **Document matching:** Identify invoices, orders and contracts that belong together.
- **Verification:** Detect inconsistencies and unsupported claims.
- **RAG chatbot:** Answer questions with citations from uploaded documents.
- **Automation:** Use n8n to process documents and notify reviewers.
- **Dashboard:** Display documents, analysis results, warnings and reports.
- **Human review:** Allow users to validate or reject detected issues.

## 3. Technology Stack

| Category | Tools |
|---|---|
| Programming | Python |
| NLP | NLTK, Regex, textstat, spaCy |
| OCR | PaddleOCR, PyMuPDF |
| AI / Deep Learning | PyTorch, Transformers |
| LLM | Qwen or Llama via LM Studio/Ollama |
| Semantic Search | Sentence Transformers |
| RAG Database | PostgreSQL + pgvector |
| Backend | FastAPI, Pydantic, SQLAlchemy |
| Background Processing | Redis + RQ |
| Frontend | React, Vite, Axios |
| Automation | n8n |
| Deployment | Docker Compose |
| Testing | Pytest, Scikit-learn |
| Version Control | Git, GitHub |

## 4. Project Architecture

```text
Documents (PDF / DOCX / Images)
             |
             v
        React Frontend
             |
             v
       FastAPI Backend
             |
             v
        Redis + RQ
             |
             v
      Document Extraction
       PyMuPDF + OCR
             |
             v
        NLP Processing
   NLTK + Regex + textstat
             |
             v
     Structured Extraction
         spaCy + LLM
             |
             v
       Document Matching
             |
             v
      Verification Engine
       Rules + NLI + AI
             |
       +-----+-----+
       |           |
       v           v
   RAG + LLM    n8n Automation
       |           |
       v           v
   AI Answers    Notifications
       |           |
       +-----+-----+
             |
             v
       React Dashboard
```

## 5. AI Verification Logic

Before comparing documents, Veritas AI must determine whether they relate to the same transaction or agreement.

The verification engine classifies claims as:

- **Supported:** Evidence supports the claim.
- **Contradicted:** Evidence conflicts with the claim.
- **Insufficient Evidence:** Available documents do not establish whether the claim is correct.

Different values in unrelated documents are not automatically contradictions.

## 6. Development Roadmap

### Phase 1 — NLP Fundamentals (Week 1)
Learn Python text processing, NLTK, Regex and textstat.  
**Deliverable:** Text-analysis script.

### Phase 2 — OCR & Document Processing (Week 2)
Learn PyMuPDF, PaddleOCR and DOCX extraction.  
**Deliverable:** Document-reading pipeline.

### Phase 3 — Structured Extraction (Week 3)
Learn spaCy, LLM-based extraction and Pydantic validation.  
**Deliverable:** Structured document information in JSON.

### Phase 4 — Document Matching (Week 4)
Identify related invoices, orders, contracts and document versions.  
**Deliverable:** Document relationship engine.

### Phase 5 — AI Verification (Week 5)
Learn Natural Language Inference, numerical verification rules and model evaluation.  
**Deliverable:** Contradiction-detection and evidence-verification engine.

### Phase 6 — RAG (Week 6)
Learn embeddings, vector databases, semantic search and RAG.  
**Deliverable:** Document question-answering system with citations.

### Phase 7 — Backend (Week 7)
Integrate FastAPI, PostgreSQL, Redis and RQ.  
**Deliverable:** Functional REST API.

### Phase 8 — Frontend (Week 8)
Build the React dashboard, document viewer and verification interface.  
**Deliverable:** Working web application.

### Phase 9 — Automation (Week 9)
Create n8n workflows for processing, notifications and human reviews.  
**Deliverable:** Automated document verification workflow.

### Phase 10 — Deployment (Week 10)
Add Docker, testing, documentation and GitHub integration.  
**Deliverable:** Portfolio-ready project.

## 7. Datasets

- **FEVER:** Claim verification.
- **SNLI / MultiNLI:** Natural Language Inference.
- **DocVQA:** Document question answering.
- **Synthetic invoices and orders:** Document matching and numerical verification.

Evaluate using precision, recall, F1-score, retrieval metrics, citation accuracy and processing time.

## 8. Minimum Viable Product (MVP)

The first working version must:

1. Upload a purchase order and a scanned invoice.
2. Read both documents.
3. Extract their important information.
4. Establish that they concern the same transaction.
5. Compare amounts, quantities and dates.
6. Detect unexplained inconsistencies.
7. Display supporting evidence.
8. Trigger an n8n notification.
9. Allow a human to review the result.

## 9. My Learning Goals

By completing the project, I want to develop skills in:

- Python programming and NLP.
- Machine Learning and Deep Learning.
- LLM integration and prompt engineering.
- Retrieval-Augmented Generation.
- OCR and document intelligence.
- Semantic search and vector databases.
- AI model evaluation.
- Backend and frontend development.
- Automation with n8n.
- Docker, testing and deployment.
- Software architecture and MLOps.

## 10. Development Principles

- Learn each concept before implementing it.
- Build one working module at a time.
- Test every important component.
- Prioritize the MVP before advanced features.
- Keep the code modular and maintainable.
- Use free and open-source tools where practical.
- Evaluate AI performance rather than assuming correctness.
- Preserve source evidence for verification decisions.
- Keep humans responsible for consequential approvals.
- Document every milestone on GitHub.

## 11. Final Objective

**Build a complete, reliable and explainable AI-powered document-processing platform that demonstrates real-world AI Engineering skills.**

The project should be suitable for academic presentation, a professional GitHub portfolio, LinkedIn, PFE internship applications and AI Engineering interviews.

---

**Next milestone:** Day 1 — Python NLP Foundations: NLTK, Regex and textstat.
