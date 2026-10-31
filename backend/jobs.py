"""Background job queue (Redis + RQ).

The API puts a job on the queue and answers immediately; a separate worker
process takes jobs off the queue and runs them. Set PROCESS_INLINE=1 to run jobs
synchronously instead (used by tests and handy for debugging).
"""

import os

from redis import Redis
from rq import Queue

redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
queue = Queue("veritas", connection=redis, is_async=os.getenv("PROCESS_INLINE") != "1")

JOB_TIMEOUT = 600  # seconds; OCR + LLM on a long document can take minutes


def enqueue_processing(document_id: int) -> None:
    # The job is referenced by its import path, so the worker can find the function. The job id
    # is fixed per document, so queueing it again while it waits does not create a second job.
    queue.enqueue("backend.pipeline.process_document", document_id, job_timeout=JOB_TIMEOUT,
                  job_id=f"process-{document_id}", at_front=False)


def enqueue_verification(invoice_id: int) -> None:
    """Re-run matching-independent verification only (after a correction or a link decision)."""
    queue.enqueue("backend.pipeline.reverify", invoice_id, job_timeout=JOB_TIMEOUT)
