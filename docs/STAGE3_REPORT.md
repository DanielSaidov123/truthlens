# Stage 3 – Database & Job Queue: Implementation Report

## 1. Scope delivered

- Prisma schema and a single reviewed migration for `jobs` and `findings`.
- PostgreSQL-backed job queue using `FOR UPDATE SKIP LOCKED`.
- Worker claim / lease / fencing-token / heartbeat / recovery.
- Retry policy: 3 attempts total, waits of 5 s and 15 s, no retry for non-transient errors.
- Database-enforced idempotency: `UNIQUE (job_id, dedupe_key)` + `ON CONFLICT DO NOTHING`.
- Storage consistency design (compensating actions, orphan janitor, missing-object handling).
- Infrastructure fixes: AI service has no PostgreSQL dependency or `DATABASE_URL`;
  healthchecks for backend, AI service, worker and frontend; centralised environment
  contract in `.env.example`; corrected Dockerfiles and ESLint setup.
- Documentation: `README.md`, `docs/ARCHITECTURE.md`, this report.

Explicitly **not** delivered (by instruction): real AI provider, URL ingestion, upload API,
frontend implementation, authentication, billing, Stage 4 work.

## 2. Services and responsibility boundaries

| Service | Queue access | Notes |
| --- | --- | --- |
| Backend (Fastify + Prisma) | Creates jobs, reads jobs/findings | Never claims or writes findings |
| Worker (Python + psycopg 3) | Claims, heartbeats, recovery, completes/fails, inserts findings | No HTTP server |
| AI service (FastAPI) | None; `DATABASE_URL` is not injected | Stateless compute |
| Frontend | None | UI shell only in Stage 3 |

Verified in the running stack:

```
AI_DATABASE_URL=None
WORKER_DATABASE_URL_SET=True
```

## 3. Database schema

Migration: `backend/prisma/migrations/20261105133205_stage3_job_queue/migration.sql`.

### `jobs`

- Enums: `JobStatus (queued|processing|completed|failed)`,
  `Verdict (ai_generated|ai_edited|likely_real|inconclusive)`.
- Retry: `attempts` (default 0), `max_attempts` (default 3), `next_attempt_at`.
- Lease: `lease_token uuid`, `lease_expires_at`, `last_heartbeat_at`.
- Errors: `error_code`, `error_message`.
- Source metadata: `storage_key`, `original_filename`, `content_type`, `size_bytes`.
- Provenance: `provider`, `model`.
- Timestamps: `created_at`, `updated_at`, `started_at`, `completed_at`.
- Indexes: `(status, next_attempt_at)`, `(status, lease_expires_at)`, `(created_at)`.
- Primary key has a database-level `gen_random_uuid()` default so raw SQL inserts work.

### `findings`

- `job_id` FK → `jobs.id` `ON DELETE CASCADE`.
- `UNIQUE (job_id, dedupe_key)` (index `findings_job_id_dedupe_key_key`).
- Index on `job_id`; JSONB `evidence`; time range in seconds.

Confirmed with `\d jobs` and `\d findings` on the running PostgreSQL 16 instance.

## 4. Queue protocol

### Claim

```sql
UPDATE jobs
SET status = 'processing',
    attempts = attempts + 1,
    lease_token = gen_random_uuid(),
    lease_expires_at = now() + make_interval(secs => $lease),
    last_heartbeat_at = now(),
    started_at = COALESCE(started_at, now()),
    updated_at = now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status = 'queued' AND next_attempt_at <= now()
  ORDER BY next_attempt_at, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id, lease_token, attempts, max_attempts, storage_key;
```

### Heartbeat

Fenced by `id AND lease_token = $token AND status = 'processing'`. Zero rows means the
lease was lost and the worker aborts without writing results.

### Complete (fenced, single transaction)

1. `UPDATE jobs ... WHERE id = $id AND lease_token = $token AND status = 'processing'`.
2. If zero rows: no findings are inserted (result discarded).
3. Otherwise insert findings with `ON CONFLICT (job_id, dedupe_key) DO NOTHING`.

### Fail (fenced)

- Transient and attempts remain: `status = 'queued'`, `next_attempt_at = now() + backoff`.
- Permanent or budget exhausted: `status = 'failed'`, `completed_at = now()`.

### Recovery

Expired `processing` rows (`lease_expires_at < now()`) are requeued, or failed with
`LEASE_EXPIRED` when `attempts >= max_attempts`.

## 5. Retry policy

| Attempt | Result of transient failure |
| --- | --- |
| 1 | wait 5 s → attempt 2 |
| 2 | wait 15 s → attempt 3 |
| 3 | `failed` |

Non-transient errors (`PermanentError`, invalid results, missing object, HTTP 4xx-class
inputs) fail immediately. Classification is unit-tested in `ai-service/tests/test_errors.py`
and `test_backoff.py`.

## 6. Idempotency

- The worker derives a deterministic `dedupe_key`; missing keys fall back to
  `code:startSec:endSec`.
- Uniqueness is enforced by PostgreSQL, not by transaction isolation alone.
- Replay and crash scenarios are tested at both queue and worker level.

## 7. Storage consistency plan

Object storage cannot join a PostgreSQL transaction, so Stage 3 defines compensating
actions (implemented later with the upload API):

1. Write the object under a server-generated key before inserting the job.
2. If the job insert fails, delete the object.
3. A janitor compares objects with `jobs.storage_key` and removes orphans after a grace
   period.
4. A job whose object is missing is failed with `error_code = 'OBJECT_MISSING'`.
5. Uploads use a temporary key followed by an atomic rename, so partial uploads are never
   visible.

## 8. Infrastructure fixes

| Fix | Result |
| --- | --- |
| Remove AI service → PostgreSQL dependency | No `depends_on`, no `DATABASE_URL`; verified in container |
| Healthchecks | backend `/health`, AI `/health`, worker liveness file, frontend HTTP |
| Environment variables | `.env.example` documents every variable; Compose defaults with `${VAR:-default}` |
| Dockerfile / lint | backend `npm ci` + `prisma generate`; frontend Dockerfile; ESLint 10 configs for both |

Compose defaults to host port `5433` for PostgreSQL. In this environment a native
PostgreSQL 18 service already listens on 5433, so verification used `POSTGRES_PORT=5544`.

## 9. Tests and results

| Suite | Command | Result |
| --- | --- | --- |
| Backend integration | `npm test` (in `backend`) | **5 passed** |
| Worker unit + integration | `python -m pytest -q` (in `ai-service`) | **43 passed** |
| Backend lint | `npm run lint` | **0 problems** |
| Backend TypeScript build | `npm run build` | **passed** |
| Frontend lint | `npx eslint .` | **0 problems** |
| Frontend production build | `npm run build` | **passed** (Webpack fallback) |

Coverage highlights:

- Concurrent claims never overlap (`SKIP LOCKED`), locked rows are skipped.
- Claim increments attempts, issues a token and records the heartbeat timestamp.
- Expired leases are requeued; exhausted budgets become `failed` with `LEASE_EXPIRED`.
- Stale fencing tokens cannot complete or fail a job, and cannot insert findings.
- Duplicate findings are rejected by the unique constraint; replay is safe.
- Deleting a job cascades to findings.
- Retry schedule is exactly 5 s then 15 s, then failure; permanent errors are not retried.
- Full worker run completes a job with `provider = "mock"`, writes one finding and stops.

## 10. Live stack verification

All Compose services reported `healthy`:

```
truthlens-postgres-1     healthy (host 5544 -> 5432)
truthlens-backend-1      healthy (3001 -> 3000)
truthlens-ai-service-1   healthy (8000)
truthlens-worker-1       healthy (liveness file)
truthlens-frontend-1     healthy (3000)
```

Endpoints:

- `GET http://localhost:3001/health` → `200 {"status":"ok"}`
- `GET http://localhost:8000/health` → `200 {"status":"ok"}`
- `GET http://localhost:3000/` → `200`, `<html lang="he" dir="rtl">`

End-to-end queue run (queued job inserted, worker claimed it):

```
status = completed | verdict = inconclusive | provider = mock
model = stage3-mock-v1 | attempts = 1 | findings = 1
```

Lease recovery run (job inserted as `processing` with an expired lease):

```
Recovered expired job ... -> queued
Claimed job ... (attempt 2/3)
status = completed | attempts = 2
```

Backend Prisma connectivity inside the Compose network was verified with
`JOBS_IN_CONTAINER=2`.

## 11. Known environment constraints

- `minio/minio` cannot be pulled here; MinIO remains an optional `s3` profile.
- The host has a native PostgreSQL 18 on port 5433; Compose verification used 5544.
- The native SWC binary is unusable, so Next.js runs with `--webpack`.

## 12. Follow-up (requires explicit approval)

Stage 4 should not start until the user approves it.
