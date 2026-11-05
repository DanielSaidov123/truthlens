from __future__ import annotations

import threading

import psycopg
import pytest

from src.worker import queue
from tests.conftest import (
    TEST_DATABASE_URL,
    count_findings,
    create_job,
    delay_seconds,
    fetch_job,
)

FINDING = {
    "type": "MOCK_FINDING",
    "start_sec": 0.0,
    "end_sec": 1.0,
    "description": "not real analysis",
    "confidence": None,
    "severity": "info",
    "evidence": {"mock": True},
}


def claim(conn: psycopg.Connection):
    job = queue.claim_next(conn, 60)
    assert job is not None
    return job


def test_claim_issues_token_and_increments_attempts(conn):
    job_id = create_job(conn)

    claimed = claim(conn)

    assert claimed.id == job_id
    assert claimed.attempts == 1
    assert claimed.lease_token
    row = fetch_job(conn, job_id)
    assert row["status"] == "processing"
    assert row["lease_token"] is not None
    assert row["last_heartbeat_at"] is not None


def test_claim_returns_none_when_queue_is_empty(conn):
    assert queue.claim_next(conn, 60) is None


def test_claim_skips_jobs_scheduled_in_the_future(conn):
    job_id = create_job(conn)
    conn.execute(
        "UPDATE jobs SET next_attempt_at = now() + interval '1 hour' WHERE id = %s",
        (job_id,),
    )

    assert queue.claim_next(conn, 60) is None


def test_claim_orders_by_next_attempt_at(conn):
    older = create_job(conn)
    conn.execute(
        "UPDATE jobs SET next_attempt_at = now() - interval '10 seconds' WHERE id = %s",
        (older,),
    )
    create_job(conn)

    assert claim(conn).id == older


def test_claim_skips_rows_locked_by_another_transaction(conn):
    first = create_job(conn)
    second = create_job(conn)

    with psycopg.connect(TEST_DATABASE_URL, autocommit=False) as other:
        other.execute("SELECT id FROM jobs WHERE id = %s FOR UPDATE", (first,))
        assert claim(conn).id == second
        other.rollback()


def test_concurrent_claims_never_overlap(conn):
    ids = {create_job(conn) for _ in range(5)}
    claimed: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(5)

    def worker() -> None:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            barrier.wait()
            job = queue.claim_next(connection, 60)
            with lock:
                if job:
                    claimed.append(job.id)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(claimed) == 5
    assert len(set(claimed)) == 5
    assert set(claimed) == ids


def test_heartbeat_requires_the_current_token(conn):
    job_id = create_job(conn)
    claimed = claim(conn)

    assert queue.heartbeat(conn, job_id, claimed.lease_token, 60) is True
    assert queue.heartbeat(conn, job_id, "00000000-0000-0000-0000-000000000000", 60) is False


def test_expired_lease_is_requeued(conn):
    job_id = create_job(conn)
    claim(conn)
    conn.execute(
        "UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
        (job_id,),
    )

    recovered = queue.recover_expired(conn)

    assert (job_id, "queued") in recovered
    row = fetch_job(conn, job_id)
    assert row["status"] == "queued"
    assert row["lease_token"] is None


def test_expired_lease_with_exhausted_budget_fails(conn):
    job_id = create_job(conn, status="processing", attempts=3, max_attempts=3)
    conn.execute(
        """
        UPDATE jobs
        SET lease_token = gen_random_uuid(),
            lease_expires_at = now() - interval '1 second'
        WHERE id = %s
        """,
        (job_id,),
    )

    recovered = queue.recover_expired(conn)

    assert (job_id, "failed") in recovered
    row = fetch_job(conn, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "LEASE_EXPIRED"


def test_recovery_leaves_active_leases_alone(conn):
    job_id = create_job(conn, status="processing", attempts=1)
    conn.execute(
        """
        UPDATE jobs
        SET lease_token = gen_random_uuid(),
            lease_expires_at = now() + interval '60 seconds'
        WHERE id = %s
        """,
        (job_id,),
    )

    assert queue.recover_expired(conn) == []


def test_complete_writes_status_and_findings(conn):
    job_id = create_job(conn)
    claimed = claim(conn)

    outcome = queue.complete_job(
        conn,
        job_id,
        claimed.lease_token,
        "inconclusive",
        [FINDING, {**FINDING, "dedupeKey": "f-2", "start_sec": 2.0, "end_sec": 3.0}],
        "mock",
        "stage3-mock-v1",
    )

    assert outcome.applied is True
    row = fetch_job(conn, job_id)
    assert row["status"] == "completed"
    assert row["verdict"] == "inconclusive"
    assert row["provider"] == "mock"
    assert row["completed_at"] is not None
    assert count_findings(conn, job_id) == 2


def test_complete_with_stale_token_writes_nothing(conn):
    job_id = create_job(conn)
    claimed = claim(conn)
    conn.execute(
        """
        UPDATE jobs
        SET lease_token = gen_random_uuid(),
            lease_expires_at = now() + interval '60 seconds'
        WHERE id = %s
        """,
        (job_id,),
    )

    outcome = queue.complete_job(
        conn, job_id, claimed.lease_token, "inconclusive", [FINDING], "mock", "m"
    )

    assert outcome.applied is False
    assert fetch_job(conn, job_id)["status"] == "processing"
    assert count_findings(conn, job_id) == 0


def test_duplicate_findings_are_rejected_by_the_database(conn):
    job_id = create_job(conn)
    claimed = claim(conn)
    queue.complete_job(
        conn, job_id, claimed.lease_token, "inconclusive", [FINDING, FINDING], "mock", "m"
    )
    assert count_findings(conn, job_id) == 1

    # Simulate a replayed completion of the same job.
    conn.execute(
        """
        UPDATE jobs
        SET status = 'processing'::"JobStatus",
            lease_token = %s::uuid,
            lease_expires_at = now() + interval '60 seconds'
        WHERE id = %s
        """,
        (claimed.lease_token, job_id),
    )
    queue.complete_job(
        conn, job_id, claimed.lease_token, "inconclusive", [FINDING], "mock", "m"
    )

    assert count_findings(conn, job_id) == 1


def test_findings_are_cascaded_when_job_is_deleted(conn):
    job_id = create_job(conn)
    claimed = claim(conn)
    queue.complete_job(
        conn, job_id, claimed.lease_token, "inconclusive", [FINDING], "mock", "m"
    )

    conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))

    assert count_findings(conn, job_id) == 0


def test_transient_failure_waits_five_then_fifteen_then_fails(conn):
    job_id = create_job(conn)

    first = claim(conn)
    assert queue.fail_job(conn, job_id, first.lease_token, "T", "boom", True, first.attempts) == "queued"
    assert 4 <= delay_seconds(conn, job_id) <= 6

    conn.execute("UPDATE jobs SET next_attempt_at = now() WHERE id = %s", (job_id,))
    second = claim(conn)
    assert second.attempts == 2
    assert queue.fail_job(conn, job_id, second.lease_token, "T", "boom", True, second.attempts) == "queued"
    assert 14 <= delay_seconds(conn, job_id) <= 16

    conn.execute("UPDATE jobs SET next_attempt_at = now() WHERE id = %s", (job_id,))
    third = claim(conn)
    assert third.attempts == 3
    assert queue.fail_job(conn, job_id, third.lease_token, "T", "boom", True, third.attempts) == "failed"

    row = fetch_job(conn, job_id)
    assert row["status"] == "failed"
    assert row["completed_at"] is not None


def test_permanent_failure_does_not_retry(conn):
    job_id = create_job(conn)
    claimed = claim(conn)

    status = queue.fail_job(
        conn, job_id, claimed.lease_token, "INVALID_RESULT", "bad", False, claimed.attempts
    )

    assert status == "failed"
    row = fetch_job(conn, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "INVALID_RESULT"


def test_failure_with_stale_token_is_ignored(conn):
    job_id = create_job(conn)
    claimed = claim(conn)
    conn.execute(
        "UPDATE jobs SET lease_token = gen_random_uuid() WHERE id = %s", (job_id,)
    )

    assert queue.fail_job(conn, job_id, claimed.lease_token, "T", "boom", False, 1) is None
    assert fetch_job(conn, job_id)["status"] == "processing"


@pytest.mark.parametrize("verdict", ["ai_generated", "ai_edited", "likely_real", "inconclusive"])
def test_all_verdicts_are_accepted(conn, verdict):
    job_id = create_job(conn)
    claimed = claim(conn)
    assert queue.complete_job(conn, job_id, claimed.lease_token, verdict, [], "mock", None).applied
    assert fetch_job(conn, job_id)["verdict"] == verdict
