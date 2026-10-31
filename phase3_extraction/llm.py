"""Thin wrapper around the local LLM served by Ollama.

Every request is bounded: a maximum answer length (a model can otherwise loop and generate
forever, keeping the GPU busy) and a network timeout. A request that hits a limit fails
with a clear error instead of hanging the worker.
"""

import os

import ollama
from pydantic import BaseModel

MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
MAX_ANSWER_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "3000"))  # ~ a 40-row table as JSON
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT", "180"))
_client = ollama.Client(host=os.getenv("OLLAMA_URL", "http://localhost:11434"), timeout=TIMEOUT_SECONDS)


class AnswerTooLong(RuntimeError):
    """The model hit the answer-length limit (usually a loop); the caller falls back to rules."""


def is_available() -> bool:
    # VERITAS_DISABLE_LLM=1 forces rule-based extraction (fast, deterministic tests).
    if os.getenv("VERITAS_DISABLE_LLM") == "1":
        return False
    try:
        return any(m.model == MODEL for m in _client.list().models)
    except Exception:
        return False


def chat(system: str, user: str, schema: type[BaseModel] | None = None) -> str:
    response = _client.chat(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        # Structured output: the model is constrained to produce JSON matching the schema.
        format=schema.model_json_schema() if schema else None,
        # qwen3 "thinks" before answering by default; slower and not needed here.
        think=False,
        # temperature 0 = always pick the most likely token -> repeatable results.
        # num_predict caps the answer length (no repeat penalty: JSON legitimately repeats keys).
        options={"temperature": 0, "num_predict": MAX_ANSWER_TOKENS},
    )
    if response.done_reason == "length":
        raise AnswerTooLong(f"The model's answer exceeded {MAX_ANSWER_TOKENS} tokens")
    return response.message.content
