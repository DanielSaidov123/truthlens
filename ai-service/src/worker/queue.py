"""PostgreSQL job queue with lease fencing.

Only the worker uses these functions. The backend creates jobs and reads
results through Prisma; the AI service never touches this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from .backoff import retry_delay


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    lease_token: str
    attempts: int
    max_attempts: int
    storage_key: str | None


@dataclass(frozen=True)
class CompleteOutcome:
    applied: bool


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection whose transactions are explicit."""
    return psycopg.connect(database_url, autocommit=True)


def recover_expired(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """Requeue expired jobs, or fail them when the retry budget is exhausted."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = CASE
                    WHEN attempts >= max_attempts THEN 'failed'::"JobStatus"
                    ELSE 'queued'::"JobStatus"
                END,
                error_code = CASE
                    WHEN attempts >= max_attempts THEN 'LEASE_EXPIRED'
                    ELSE error_code
                END,
                error_message = CASE
                    WHEN attempts >= max_attempts THEN 'Lease expired and retry budget exhausted'
                    ELSE error_message
                END,
                completed_at = CASE
                    WHEN attempts >= max_attempts THEN now()
                    ELSE completed_at
                END,
                next_attempt_at = CASE
                    WHEN attempts >= max_attempts THEN next_attempt_at
                    ELSE now()
                END,
                lease_token = NULL,
                lease_expires_at = NULL,
                updated_at = now()
            WHERE status = 'processing'::"JobStatus"
              AND lease_expires_at < now()
            RETURNING id::text, status::text
            """
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def claim_next(conn: psycopg.Connection, lease_seconds: int) -> ClaimedJob | None:
    """Atomically claim one queued job and issue a fencing token."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'processing'::"JobStatus",
                attempts = attempts + 1,
                lease_token = gen_random_uuid(),
                lease_expires_at = now() + make_interval(secs => %s),
                last_heartbeat_at = now(),
                started_at = COALESCE(started_at, now()),
                updated_at = now()
            WHERE id = (
                SELECT id
                FROM jobs
                WHERE status = 'queued'::"JobStatus"
                  AND next_attempt_at <= now()
                ORDER BY next_attempt_at, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id::text, lease_token::text, attempts, max_attempts, storage_key
            """,
            (lease_seconds,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return ClaimedJob(
            id=row[0],
            lease_token=row[1],
            attempts=row[2],
            max_attempts=row[3],
            storage_key=row[4],
        )


def heartbeat(
    conn: psycopg.Connection,
    job_id: str,
    lease_token: str,
    lease_seconds: int,
) -> bool:
    """Extend the lease. False means the worker no longer owns the job."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET lease_expires_at = now() + make_interval(secs => %s),
                last_heartbeat_at = now(),
                updated_at = now()
            WHERE id = %s
              AND lease_token = %s
              AND status = 'processing'::"JobStatus"
            """,
            (lease_seconds, job_id, lease_token),
        )
        return cur.rowcount == 1


def _normalise_finding(finding: dict[str, Any]) -> tuple:
    finding_type = str(finding["type"])
    start_sec = float(finding["start_sec"])
    end_sec = float(finding["end_sec"])
    dedupe_key = str(
        finding.get("dedupeKey") or f"{finding_type}:{start_sec:.3f}:{end_sec:.3f}"
    )
    evidence = finding.get("evidence")
    return (
        dedupe_key,
        finding_type,
        str(finding.get("title") or finding_type),
        finding.get("description"),
        start_sec,
        end_sec,
        finding.get("confidence"),
        finding.get("severity"),
        Jsonb(evidence) if evidence is not None else None,
    )


def complete_job(
    conn: psycopg.Connection,
    job_id: str,
    lease_token: str,
    verdict: str,
    findings: Iterable[dict[str, Any]],
    provider: str,
    model: str | None,
) -> CompleteOutcome:
    """Write the result only while the fencing token is still valid.

    The status update and the findings insert share one transaction. If the
    fenced update affects no rows, nothing is written.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'completed'::"JobStatus",
                verdict = %s::"Verdict",
                provider = %s,
                model = %s,
                error_code = NULL,
                error_message = NULL,
                completed_at = now(),
                lease_token = NULL,
                lease_expires_at = NULL,
                last_heartbeat_at = now(),
                updated_at = now()
            WHERE id = %s
              AND lease_token = %s
              AND status = 'processing'::"JobStatus"
            RETURNING id
            """,
            (verdict, provider, model, job_id, lease_token),
        )
        if cur.fetchone() is None:
            return CompleteOutcome(applied=False)

        for finding in findings:
            cur.execute(
                """
                INSERT INTO findings
                    (job_id, dedupe_key, code, title, description,
                     start_sec, end_sec, confidence, severity, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id, dedupe_key) DO NOTHING
                """,
                (job_id, *_normalise_finding(finding)),
            )

        return CompleteOutcome(applied=True)


def fail_job(
    conn: psycopg.Connection,
    job_id: str,
    lease_token: str,
    code: str,
    message: str,
    transient: bool,
    attempts_made: int,
) -> str | None:
    """Record a failure. Returns the resulting status, or None if fenced out."""
    delay = retry_delay(attempts_made) if transient else None

    with conn.transaction(), conn.cursor() as cur:
        if delay is not None:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'queued'::"JobStatus",
                    next_attempt_at = now() + make_interval(secs => %s),
                    error_code = %s,
                    error_message = %s,
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                WHERE id = %s
                  AND lease_token = %s
                  AND status = 'processing'::"JobStatus"
                RETURNING status::text
                """,
                (delay, code, message[:2000], job_id, lease_token),
            )
        else:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'failed'::"JobStatus",
                    error_code = %s,
                    error_message = %s,
                    completed_at = now(),
                    lease_token = NULL,
                    lease_expires_at = NULL,
                    updated_at = now()
                WHERE id = %s
                  AND lease_token = %s
                  AND status = 'processing'::"JobStatus"
                RETURNING status::text
                """,
                (code, message[:2000], job_id, lease_token),
            )

        row = cur.fetchone()
        return row[0] if row else None
