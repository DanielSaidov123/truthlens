"""Execute one claimed job: analyze, then commit or fail under the lease fence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import psycopg
from pydantic import ValidationError

from ..contract import AnalysisResult, Finding, to_persisted_verdict
from . import queue
from .config import WorkerConfig
from .errors import PermanentError, error_code, is_transient
from .heartbeat import Heartbeat
from .queue import ClaimedJob

logger = logging.getLogger(__name__)

AnalyzeFn = Callable[[ClaimedJob], dict[str, Any]]


@dataclass(frozen=True)
class JobOutcome:
    status: str
    lease_lost: bool = False


def validate_result(result: dict[str, Any]) -> tuple[str, list[Finding], str, str | None]:
    """Validate an analysis result against the provider-independent contract."""
    try:
        parsed = AnalysisResult.model_validate(result)
    except ValidationError as exc:
        raise PermanentError(f"Invalid analysis result: {exc}", code="INVALID_RESULT") from exc

    return parsed.verdict, list(parsed.findings), parsed.provider, parsed.model


def run_claimed_job(
    conn: psycopg.Connection,
    job: ClaimedJob,
    config: WorkerConfig,
    analyze: AnalyzeFn,
) -> JobOutcome:
    heartbeat = Heartbeat(
        database_url=config.database_url,
        job_id=job.id,
        lease_token=job.lease_token,
        lease_seconds=config.lease_seconds,
        interval_seconds=config.heartbeat_seconds,
    )
    heartbeat.start()

    try:
        result = analyze(job)

        if heartbeat.lost:
            logger.warning("Discarding result for job %s: lease lost", job.id)
            return JobOutcome(status="lease_lost", lease_lost=True)

        verdict, findings, provider, model = validate_result(result)
        outcome = queue.complete_job(
            conn,
            job.id,
            job.lease_token,
            to_persisted_verdict(verdict),
            [finding.model_dump(mode="json") for finding in findings],
            provider,
            model,
        )
        if not outcome.applied:
            logger.warning("Discarding result for job %s: fencing token rejected", job.id)
            return JobOutcome(status="lease_lost", lease_lost=True)
        return JobOutcome(status="completed")

    except Exception as exc:
        if heartbeat.lost:
            logger.warning("Discarding failure for job %s: lease lost", job.id)
            return JobOutcome(status="lease_lost", lease_lost=True)

        transient = is_transient(exc)
        status = queue.fail_job(
            conn,
            job.id,
            job.lease_token,
            error_code(exc),
            str(exc),
            transient=transient,
            attempts_made=job.attempts,
        )
        if status is None:
            logger.warning("Failure not recorded for job %s: fencing token rejected", job.id)
            return JobOutcome(status="lease_lost", lease_lost=True)

        logger.info(
            "Job %s failed (attempt %s/%s, transient=%s) -> %s",
            job.id,
            job.attempts,
            job.max_attempts,
            transient,
            status,
        )
        return JobOutcome(status=status)

    finally:
        heartbeat.stop()
