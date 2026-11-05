"""Background heartbeat that keeps a job lease alive."""

from __future__ import annotations

import logging
import threading

from . import queue

logger = logging.getLogger(__name__)


class Heartbeat:
    """Extend a lease every ``interval`` seconds using its own connection."""

    def __init__(
        self,
        database_url: str,
        job_id: str,
        lease_token: str,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._database_url = database_url
        self._job_id = job_id
        self._lease_token = lease_token
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._lost = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="job-heartbeat")

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        connection = queue.connect(self._database_url)
        try:
            while not self._stop.wait(self._interval_seconds):
                try:
                    if not queue.heartbeat(
                        connection,
                        self._job_id,
                        self._lease_token,
                        self._lease_seconds,
                    ):
                        logger.warning("Lease lost for job %s", self._job_id)
                        self._lost.set()
                        return
                except Exception:  # pragma: no cover - infrastructure failure
                    logger.exception("Heartbeat failed for job %s", self._job_id)
        finally:
            connection.close()
