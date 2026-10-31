"""Start the background worker that processes uploaded documents.

Usage (from the project root, in its own terminal):
    python -m backend.worker

RQ's default worker forks a child process per job, which Windows cannot do.
SimpleWorker runs jobs in this process instead, so the AI models stay loaded in
memory between jobs, and TimerDeathPenalty enforces job timeouts with a timer
thread instead of the Unix-only SIGALRM signal.
"""

import logging

from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from backend.jobs import queue, redis


class WindowsWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    WindowsWorker([queue], connection=redis).work()


if __name__ == "__main__":
    main()
