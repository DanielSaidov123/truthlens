# TruthLens Architecture

## 1. Services and responsibilities

| Service | Runtime | Owns | Must not |
| --- | --- | --- | --- |
| `frontend` | Next.js 16 + React 19 + TypeScript | Hebrew/RTL UI, file selection, status display | Access PostgreSQL, object storage, or the AI provider directly |
| `backend` | Node.js 22 + Fastify 5 + TypeScript | Public API, job creation, uploads, reads results | Run analysis, write findings |
| `ai-service` | Python 3.12 + FastAPI | Provider-independent result contract, model execution | Access PostgreSQL or the job queue |
| `worker` | Python 3.12 process | Claim jobs, lease/heartbeat, run analysis, persist findings, retry/fail | Expose HTTP, serve users, create uploads |
| `postgres` | PostgreSQL 16 | Source of truth: jobs, findings; job queue | — |
| `minio` (optional) | S3-compatible | Object storage in local dev (when the registry allows it) | Be required for development |

The AI service is a stateless compute service. It receives a storage reference or bytes and
returns a result; it never reads or writes the queue.

## 1.1 Component contracts (KAN-13)

Each component has a single responsibility and a defined interface.

| Component | Receives | Returns / writes | Talks to | Must not |
| --- | --- | --- | --- | --- |
| Frontend | User input (file/URL) | HTTP requests to Backend | Backend only | DB, storage, AI provider |
| Backend (Fastify) | HTTP requests | JSON responses; creates/reads jobs | Postgres (Prisma), Storage | Run analysis, write findings |
| Worker | DB rows (`queued`) | Status updates, findings | Postgres (psycopg), Storage, AI service | Serve HTTP, create uploads |
| AI service | Storage reference / bytes (Stage 4) | Result contract (verdicts, findings, confidence, provider, model) | None (stateless) | DB, queue |
| Postgres | SQL from backend/worker | Rows, locks | backend, worker | — |
| Storage (local/S3) | Bytes / keys | Bytes / URLs | backend, worker | Be required for dev |

### Architectural decisions

- **ADR-1 — PostgreSQL as the queue.** Use `FOR UPDATE SKIP LOCKED` on the existing
  Postgres instead of an external broker. Simpler, transactional with job state,
  no new infrastructure. Recovery is handled by lease expiry.
- **ADR-2 — Separate AI service (stateless).** Kept as a separate Python process
  even in Stage 3 (mock provider) to preserve provider independence and a clean
  compute boundary. It has no DB access.
- **ADR-3 — Separate worker process.** Long-running lease/heartbeat/recovery
  belongs in a dedicated process, not in the stateless AI service.
- **ADR-4 — Lease fencing.** Every worker write is gated by `lease_token` to
  prevent stale writes after lease loss.
- **ADR-5 — Database-enforced idempotency.** `UNIQUE (job_id, dedupe_key)` plus
  `ON CONFLICT DO NOTHING`; correctness does not depend on transaction isolation alone.
- **ADR-6 — Status only, no progress percentage.** The job model has no progress
  field; the frontend must not invent progress values.
- **ADR-7 — No external queue/broker in Stage 3.** The Postgres-backed queue is
  sufficient for the MVP; an external broker would add infrastructure without
  proven need. Revisit if throughput demands it.

### Simplicity notes

- The Python AI service is retained (ADR-2) but does not access Postgres.
- No external queue broker is introduced (ADR-7).
- Storage is an abstraction (`StorageDriver`) with a local default; S3/MinIO is optional.

## 2. Data flow

```
Frontend ──HTTP──> Backend ──Storage──> object
                     │
                     └── INSERT jobs (queued) ──> PostgreSQL

Worker ──claim (SKIP LOCKED, lease token)──> jobs
   ├── reads object from Storage
   ├── HTTP ──> AI Service (stateless)
   └── TX: fenced status update + INSERT findings ON CONFLICT DO NOTHING

Backend ──SELECT jobs + findings──> Frontend
```

Today the queue is implemented; the upload API and frontend flow are later stages.

## 3. Database schema

### `jobs`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | uuid PK | Job identifier |
| `status` | enum `queued\|processing\|completed\|failed` | Lifecycle |
| `verdict` | enum, nullable | `ai_generated\|ai_edited\|likely_real\|inconclusive` |
| `attempts` | int, default 0 | Incremented on every claim |
| `maxAttempts` | int, default 3 | Retry budget |
| `nextAttemptAt` | timestamptz | Earliest time the job may be claimed |
| `leaseToken` | uuid, nullable | Fencing token of the current owner |
| `leaseExpiresAt` | timestamptz, nullable | Lease deadline extended by heartbeat |
| `lastHeartbeatAt` | timestamptz, nullable | Last successful heartbeat |
| `errorCode`, `errorMessage` | text, nullable | Failure details |
| `storageKey`, `originalFilename`, `contentType`, `sizeBytes` | — | Source metadata |
| `provider`, `model` | text, nullable | Provenance (mock vs real) |
| `createdAt`, `updatedAt`, `startedAt`, `completedAt` | timestamptz | Timestamps |

Indexes: `(status, nextAttemptAt)` for claims, `(status, leaseExpiresAt)` for recovery,
`(createdAt)` for listing. Primary keys have a database-level `gen_random_uuid()` default,
so the worker can insert rows with raw SQL while Prisma still generates ids client-side.

The worker validates the provider-independent result contract verdicts
(`likely_ai_generated`, `possible_ai_edit`, `no_clear_ai_evidence`, `inconclusive`)
via `ai-service/src/contract.py` and maps them to the persisted enum values above
(`likely_ai_generated → ai_generated`, `possible_ai_edit → ai_edited`,
`no_clear_ai_evidence → likely_real`, `inconclusive → inconclusive`). The mapping is
a backward compatibility adaptation for the storage layer, not a claim of absolute
certainty; `likely_real` is never surfaced to users as proof of authenticity.

### Result contract (KAN-15)

The AI service owns the central, provider-independent result contract:

- **Verdicts:** `likely_ai_generated`, `possible_ai_edit`, `no_clear_ai_evidence`, `inconclusive`.
- **Confidence:** numeric in `[0, 1]` only when calibrated; `null` otherwise. Provider
  scores are never presented as probabilities without calibration.
- **Findings:** `type`, `start_sec`, `end_sec`, `description`, optional `confidence`,
  `evidence`, `severity`.
- **Result-level fields:** `verdict`, `confidence`, `summary`, `findings`, `limitations`,
  `analyzed_at`, `provider`, `model`.

Job-level identifiers reuse the existing `jobs` row (`analysisId = Job.id`,
`status = JobStatus`); `summary` and `limitations` are result/DTO-level fields and are
not persisted in this stage.

### `findings`

| Column | Type | Purpose |
| --- | --- | --- |
| `id` | uuid PK | Finding identifier |
| `jobId` | uuid FK → `jobs.id` `ON DELETE CASCADE` | Parent job |
| `dedupeKey` | text | Deterministic key from the finding payload |
| `code`, `title`, `description` | text | Finding content |
| `startSec`, `endSec` | double precision | Seconds from the start of the video |
| `confidence` | double, nullable | Only when grounded |
| `severity` | text, nullable | Optional classification |
| `evidence` | jsonb, nullable | Raw evidence |
| `createdAt` | timestamptz | Timestamp |

**Idempotency is enforced by the database:** `UNIQUE (job_id, dedupe_key)`. The worker also
writes findings with `ON CONFLICT (job_id, dedupe_key) DO NOTHING`, so a replayed or crashed
execution cannot create duplicates even outside a single transaction.

## 4. Queue protocol

### Claim

```sql
UPDATE jobs
SET status = 'processing'::"JobStatus",
    attempts = attempts + 1,
    lease_token = gen_random_uuid(),
    lease_expires_at = now() + make_interval(secs => $lease),
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
RETURNING id::text, lease_token::text, attempts, max_attempts, storage_key;
```

Expired `processing` jobs are **not** claimed directly. They are first requeued (or failed)
by `recover_expired` (see §4 Recovery), which sets `status = 'queued'` and clears the
lease. Only then can `claim_next` pick them up. A job that already consumed
`maxAttempts` attempts is moved to `failed` with `error_code = 'LEASE_EXPIRED'`.

### Heartbeat

```sql
UPDATE jobs
SET lease_expires_at = now() + $lease,
    last_heartbeat_at = now(),
    updated_at = now()
WHERE id = $id AND lease_token = $token AND status = 'processing';
```

Zero rows means the worker lost the lease and must abort without writing results.

### Complete (fenced)

```sql
-- inside one transaction
UPDATE jobs
SET status = 'completed', verdict = $verdict, provider = $provider, model = $model,
    completed_at = now(), lease_token = NULL, lease_expires_at = NULL, updated_at = now()
WHERE id = $id AND lease_token = $token AND status = 'processing'
RETURNING id;
```

If the update affects 0 rows, the transaction is rolled back and no findings are inserted.

### Fail

Same fencing predicate. Transient failures set `status = 'queued'`, `next_attempt_at = now() + backoff`
while attempts remain; otherwise `status = 'failed'` with the error code/message.

## 5. Retry policy

Exactly **3 attempts total**:

| Attempt | On transient failure |
| --- | --- |
| 1 | wait 5 s, then attempt 2 |
| 2 | wait 15 s, then attempt 3 |
| 3 | `failed` (no further wait) |

Non-transient errors are never retried; the job fails immediately. Transient classification
lives in the worker error module and is unit-tested (timeouts, connection errors, HTTP 5xx).
Permanent examples: unsupported/invalid media, malformed provider response, HTTP 4xx.

## 6. Lease fencing

`lease_token` is generated on every claim. Every write performed by a worker includes
`AND lease_token = $claimedToken`. If another worker reclaimed the job after lease expiry,
the old worker's writes affect zero rows, so it cannot overwrite the new owner's status or
insert findings. This is enforced in the same transaction as the findings insert.

## 7. Storage consistency (design; upload API not implemented in Stage 3)

Object storage and PostgreSQL cannot share a transaction, so consistency is achieved with
compensating actions:

1. Write the object under a server-generated key (`analyses/<uuid>/<uuid>.<ext>`) first.
2. Insert the job row. If the insert fails, delete the object.
3. If the process dies before cleanup, a janitor compares objects against `jobs.storage_key`
   and deletes orphans older than a grace period.
4. If a job exists but its object is missing, mark the job `failed` with
   `error_code = 'OBJECT_MISSING'`.
5. Uploads are written to a temp key and atomically renamed before the job row is created;
   partial uploads are never visible.

The storage contract (`StorageDriver`) hides local vs S3/MinIO: `put`, `getStream`, `delete`,
`exists`, `getReadUrl`. The local driver serves bytes through the backend (no signed URL);
the S3 driver returns a short-lived signed URL.

## 8. Migrations

Prisma owns the schema and migrations (`backend/prisma/migrations`).

```bash
cd backend
DATABASE_URL=postgresql://truthlens:truthlens@127.0.0.1:5433/truthlens npx prisma migrate dev
DATABASE_URL=... npx prisma migrate deploy   # CI / production
```

The backend image runs `prisma generate` at build time. Migrations are applied explicitly,
never silently on application start.

## 9. Environment variables

See `.env.example`. Key values:

| Variable | Used by | Notes |
| --- | --- | --- |
| `DATABASE_URL` | backend, worker | Inside Docker the host is `postgres`; from the host use `127.0.0.1:5433` |
| `TEST_DATABASE_URL` | integration tests | Separate database (`truthlens_test`) |
| `STORAGE_DRIVER`, `STORAGE_LOCAL_ROOT`, `S3_*` | backend | Storage contract |
| `AI_PROVIDER` | ai-service | `mock` only in Stage 3 |
| `AI_SERVICE_URL` | worker | Internal URL `http://ai-service:8000` |
| `WORKER_POLL_INTERVAL_SECONDS`, `WORKER_LEASE_SECONDS`, `WORKER_HEARTBEAT_SECONDS`, `WORKER_MAX_ATTEMPTS` | worker | Queue tuning |

## 10. Test strategy

- **Unit (no DB):** retry classification, backoff schedule, fencing predicates, result contract.
- **PostgreSQL integration:** migrations from an empty database, constraints, concurrent claims
  (`SKIP LOCKED`), lease expiry recovery, retry transitions, fenced writes, duplicate findings.
- **Worker integration:** full job execution with a deterministic mock provider, replay safety,
  crash simulation, heartbeat loss.
- **Contract:** AI service output validated against the shared schema.
- **E2E smoke (later stage):** upload → poll → completed with a mock-marked result.

## 11. Non-goals for Stage 3

No real AI provider, no URL ingestion, no upload API, no frontend implementation, no auth,
no billing.
