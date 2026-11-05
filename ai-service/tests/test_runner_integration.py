from __future__ import annotations

import threading
import time

import pytest

from src.worker import queue
from src.worker.analysis import mock_analyze
from src.worker.config import WorkerConfig
from src.worker.errors import PermanentError, TransientError
from src.worker.runner import run_claimed_job
from tests.conftest import TEST_DATABASE_URL, count_findings, create_job, fetch_job


@pytest.fixture()
def config(tmp_path) -> WorkerConfig:
    return WorkerConfig(
        database_url=TEST_DATABASE_URL,
        poll_interval_seconds=0.05,
        lease_seconds=2,
        heartbeat_seconds=0.05,
        max_attempts=3,
        alive_file=str(tmp_path / "worker-alive"),
    )


def claim(conn):
    job = queue.claim_next(conn, 2)
    assert job is not None
    return job


def test_runner_completes_job_with_mock_provider(conn, config):
    job_id = create_job(conn)
    job = claim(conn)

    outcome = run_claimed_job(conn, job, config, mock_analyze)

    assert outcome.status == "completed"
    row = fetch_job(conn, job_id)
    assert row["status"] == "completed"
    assert row["provider"] == "mock"
    assert row["verdict"] == "inconclusive"
    assert count_findings(conn, job_id) == 1


def test_runner_replay_does_not_duplicate_findings(conn, config):
    job_id = create_job(conn)
    job = claim(conn)
    first = run_claimed_job(conn, job, config, mock_analyze)
    assert first.status == "completed"

    # Simulate a replayed execution that still holds the original token.
    conn.execute(
        """
        UPDATE jobs
        SET status = 'processing'::"JobStatus",
            lease_token = %s::uuid,
            lease_expires_at = now() + interval '60 seconds'
        WHERE id = %s
        """,
        (job.lease_token, job_id),
    )
    outcome = queue.complete_job(
        conn,
        job_id,
        job.lease_token,
        "inconclusive",
        mock_analyze(job)["findings"],
        "mock",
        "stage3-mock-v1",
    )

    assert outcome.applied is True
    assert count_findings(conn, job_id) == 1


def test_runner_retries_transient_errors_until_budget_is_exhausted(conn, config):
    job_id = create_job(conn)

    def always_transient(_job):
        raise TransientError("temporary model outage")

    for expected_attempt in (1, 2):
        conn.execute("UPDATE jobs SET next_attempt_at = now() WHERE id = %s", (job_id,))
        job = claim(conn)
        assert job.attempts == expected_attempt
        outcome = run_claimed_job(conn, job, config, always_transient)
        assert outcome.status == "queued"
        assert fetch_job(conn, job_id)["error_code"] == "TRANSIENT_ERROR"

    conn.execute("UPDATE jobs SET next_attempt_at = now() WHERE id = %s", (job_id,))
    third = claim(conn)
    assert third.attempts == 3
    outcome = run_claimed_job(conn, third, config, always_transient)
    assert outcome.status == "failed"
    assert fetch_job(conn, job_id)["status"] == "failed"


def test_runner_does_not_retry_permanent_errors(conn, config):
    job_id = create_job(conn)
    job = claim(conn)

    def broken(_job):
        raise PermanentError("invalid media", code="INVALID_MEDIA")

    outcome = run_claimed_job(conn, job, config, broken)

    assert outcome.status == "failed"
    row = fetch_job(conn, job_id)
    assert row["error_code"] == "INVALID_MEDIA"
    assert row["attempts"] == 1


def test_runner_rejects_malformed_results(conn, config):
    job_id = create_job(conn)
    job = claim(conn)

    outcome = run_claimed_job(conn, job, config, lambda _job: {"verdict": "fake"})

    assert outcome.status == "failed"
    assert fetch_job(conn, job_id)["error_code"] == "INVALID_RESULT"


def test_runner_discards_result_when_lease_was_stolen(conn, config):
    job_id = create_job(conn)
    job = claim(conn)
    conn.execute(
        """
        UPDATE jobs
        SET lease_token = gen_random_uuid(),
            lease_expires_at = now() + interval '60 seconds'
        WHERE id = %s
        """,
        (job_id,),
    )

    outcome = run_claimed_job(conn, job, config, mock_analyze)

    assert outcome.lease_lost is True
    assert outcome.status == "lease_lost"
    assert fetch_job(conn, job_id)["status"] == "processing"
    assert count_findings(conn, job_id) == 0


def test_run_forever_processes_a_queued_job(conn, config):
    from src.worker.worker import run_forever

    job_id = create_job(conn)
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_forever, args=(config, mock_analyze, stop_event), daemon=True
    )
    thread.start()

    deadline = time.time() + 10
    while time.time() < deadline:
        row = fetch_job(conn, job_id)
        if row["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)

    stop_event.set()
    thread.join(timeout=5)

    assert fetch_job(conn, job_id)["status"] == "completed"
    assert thread.is_alive() is False
