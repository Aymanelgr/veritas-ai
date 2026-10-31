# Backend image, used by both the API and the worker containers.
FROM python:3.12-slim

# System libraries OpenCV (used by PaddleOCR) needs at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU build of PyTorch by default: small and runs anywhere. For an NVIDIA GPU, build with
#   docker compose build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch --index-url ${TORCH_INDEX}

# Dependencies first: Docker caches this layer, so code changes don't reinstall everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm \
    && python -c "import nltk; [nltk.download(r, download_dir='/usr/share/nltk_data') for r in ('punkt_tab', 'stopwords')]"

COPY alembic.ini .
COPY migrations migrations
COPY db db
COPY backend backend
COPY phase1_nlp phase1_nlp
COPY phase2_documents phase2_documents
COPY phase3_extraction phase3_extraction
COPY phase4_matching phase4_matching
COPY phase5_verification phase5_verification
COPY phase6_rag phase6_rag

# AI models (OCR, embeddings, NLI) download on first use into this volume.
ENV HF_HOME=/models/huggingface PADDLE_PDX_CACHE_HOME=/models/paddlex PYTHONUNBUFFERED=1

# Process documents with restricted privileges: an unprivileged user that can write only
# to the upload storage and the model cache, never to the application code.
RUN useradd --create-home --uid 10001 veritas \
    && mkdir -p /models /app/storage \
    && chown -R veritas:veritas /models /app/storage
USER veritas
VOLUME ["/models", "/app/storage"]

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
