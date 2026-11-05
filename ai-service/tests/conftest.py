from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://truthlens:truthlens@127.0.0.1:5433/truthlens_test",
)


@pytest.fixture()
def conn():
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("TRUNCATE TABLE findings, jobs CASCADE")
        yield connection


def create_job(
    conn: psycopg.Connection,
    *,
    status: str = "queued",
    attempts: int = 0,
    max_attempts: int = 3,
) -> str:
    row = conn.execute(
        """
        INSERT INTO jobs (status, attempts, max_attempts)
        VALUES (%s::"JobStatus", %s, %s)
        RETURNING id::text
        """,
        (status, attempts, max_attempts),
    ).fetchone()
    assert row is not None
    return row[0]


def fetch_job(conn: psycopg.Connection, job_id: str) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        assert row is not None
        return row


def count_findings(conn: psycopg.Connection, job_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM findings WHERE job_id = %s", (job_id,)
    ).fetchone()
    assert row is not None
    return row[0]


def delay_seconds(conn: psycopg.Connection, job_id: str) -> float:
    row = conn.execute(
        "SELECT EXTRACT(EPOCH FROM (next_attempt_at - now())) FROM jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert row is not None
    return float(row[0])
