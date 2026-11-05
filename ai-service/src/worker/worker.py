"""TruthLens worker process.

Separate from the FastAPI server. Claims jobs from PostgreSQL, keeps the lease
alive with heartbeats, and writes results under a fencing token.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

import psycopg

from . import queue
from .analysis import mock_analyze
from .config import WorkerConfig
from .runner import AnalyzeFn, run_claimed_job

logger = logging.getLogger("truthlens.worker")


def touch_alive(path: str) -> None:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(time.time()))
    except OSError:  # pragma: no cover - best effort only
        logger.exception("Could not update worker liveness file")


def run_forever(
    config: WorkerConfig,
    analyze: AnalyzeFn = mock_analyze,
    stop_event: threading.Event | None = None,
) -> None:
    stop_event = stop_event or threading.Event()
    connection = queue.connect(config.database_url)

    try:
        while not stop_event.is_set():
            try:
                recovered = queue.recover_expired(connection)
                for job_id, status in recovered:
                    logger.warning("Recovered expired job %s -> %s", job_id, status)

                job = queue.claim_next(connection, config.lease_seconds)
                if job is None:
                    stop_event.wait(config.poll_interval_seconds)
                else:
                    logger.info(
                        "Claimed job %s (attempt %s/%s)",
                        job.id,
                        job.attempts,
                        job.max_attempts,
                    )
                    run_claimed_job(connection, job, config, analyze)

            except psycopg.OperationalError:
                logger.exception("Database connection lost; reconnecting")
                try:
                    connection.close()
                except Exception:  # pragma: no cover - already broken
                    pass
                stop_event.wait(config.poll_interval_seconds)
                connection = queue.connect(config.database_url)
            except Exception:  # pragma: no cover - defensive loop guard
                logger.exception("Worker loop error")
                stop_event.wait(config.poll_interval_seconds)

            touch_alive(config.alive_file)
    finally:
        connection.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = WorkerConfig.from_env()
    stop_event = threading.Event()

    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("Received signal %s; shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    run_forever(config, stop_event=stop_event)


if __name__ == "__main__":
    main()
