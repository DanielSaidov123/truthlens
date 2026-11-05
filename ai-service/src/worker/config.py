"""Worker configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    poll_interval_seconds: float = 1.0
    lease_seconds: int = 60
    heartbeat_seconds: float = 10.0
    max_attempts: int = 3
    alive_file: str = "/tmp/worker-alive"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required")

        return cls(
            database_url=database_url,
            poll_interval_seconds=float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "1")),
            lease_seconds=int(os.environ.get("WORKER_LEASE_SECONDS", "60")),
            heartbeat_seconds=float(os.environ.get("WORKER_HEARTBEAT_SECONDS", "10")),
            max_attempts=int(os.environ.get("WORKER_MAX_ATTEMPTS", "3")),
            alive_file=os.environ.get("WORKER_ALIVE_FILE", "/tmp/worker-alive"),
        )
