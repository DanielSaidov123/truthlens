# TruthLens

TruthLens analyses videos and reports whether they look AI-generated or AI-edited.
The UI is Hebrew/RTL; the product is built as independently deployable services.

## Status

**Stage 3 – Database & Job Queue (current).** Implemented: PostgreSQL schema and
migrations, a PostgreSQL-backed job queue with `FOR UPDATE SKIP LOCKED`, leases with
fencing tokens, heartbeat and recovery, retry policy, database-enforced finding
idempotency, and integration tests.

Not implemented yet (by design): upload API, frontend flows, real AI provider, URL
ingestion, authentication, billing.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design,
[`docs/STAGE3_REPORT.md`](docs/STAGE3_REPORT.md) for the implementation report and test results,
[`docs/PRODUCT_VISION.md`](docs/PRODUCT_VISION.md) for product vision and goals, and
[`AGENTS.md`](AGENTS.md) for OpenCode working instructions.

## Services

| Service | Stack | Host port | Responsibility |
| --- | --- | --- | --- |
| `frontend` | Next.js 16 + React 19 + TS | `3000` | Hebrew/RTL UI shell |
| `backend` | Node.js 22 + Fastify 5 + Prisma | `3001` | Public API, job creation, reads results |
| `ai-service` | Python 3.12 + FastAPI | `8000` | Stateless analysis contract (no DB) |
| `worker` | Python 3.12 process | internal | Claims jobs, lease/heartbeat, persists findings |
| `postgres` | PostgreSQL 16 | `5433`\* | Source of truth and job queue |
| `minio` | MinIO (optional profile) | `9000/9001` | S3-compatible storage for local dev |

\* Configurable with `POSTGRES_PORT`; defaults to `5433`. Inside the Compose network the
database is always `postgres:5432`.

## Quick start

```bash
cp .env.example .env
docker compose up -d --build
```

If host port `5433` is already taken, pick another free port:

```powershell
$env:POSTGRES_PORT=5544; docker compose up -d --build
```

Then use the same port in `DATABASE_URL` / `TEST_DATABASE_URL`.

Apply migrations once the database is healthy:

```powershell
cd backend
$env:DATABASE_URL="postgresql://truthlens:truthlens@127.0.0.1:5433/truthlens"
npx prisma migrate deploy
```

Migrations are never applied automatically by the application.

### Health endpoints

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:3001/health` → `{"status":"ok"}`
- AI Service: `http://localhost:8000/health` → `{"status":"ok"}`
- Worker: Docker healthcheck based on `/tmp/worker-alive` (no HTTP)

## Database

Prisma owns the schema and migrations:

```bash
cd backend
npx prisma migrate dev --name <change>   # development
npx prisma migrate deploy                # CI / production
npx prisma generate                      # client generation
```

Tables: `jobs`, `findings`. Key guarantees:

- `findings.job_id` references `jobs.id` with `ON DELETE CASCADE`.
- `UNIQUE (job_id, dedupe_key)` prevents duplicate findings at the database level.
- Queue indexes: `(status, next_attempt_at)` and `(status, lease_expires_at)`.
- `lease_token` fences every worker write.

## Job queue semantics

- Claim: `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`; every claim
  increments `attempts` and issues a new `lease_token`.
- Heartbeat every 10 s extends `lease_expires_at`; a lost lease aborts all writes.
- Recovery: expired `processing` jobs return to `queued`, or become `failed` with
  `LEASE_EXPIRED` when the retry budget is exhausted.
- Retry: 3 attempts total, waits of 5 s and 15 s; non-transient errors fail immediately.
- Idempotency: `ON CONFLICT (job_id, dedupe_key) DO NOTHING` plus the unique constraint.

Environment tuning: `WORKER_POLL_INTERVAL_SECONDS`, `WORKER_LEASE_SECONDS`,
`WORKER_HEARTBEAT_SECONDS`, `WORKER_MAX_ATTEMPTS`.

## Tests

### Backend (Node test runner + Prisma)

Create the test database once:

```powershell
docker exec truthlens-postgres-1 psql -U truthlens -d postgres -c "CREATE DATABASE truthlens_test"
cd backend
$env:DATABASE_URL="postgresql://truthlens:truthlens@127.0.0.1:5433/truthlens_test"
npx prisma migrate deploy
npm test
```

### Worker / queue (pytest)

```powershell
cd ai-service
pip install -r requirements-dev.txt
$env:TEST_DATABASE_URL="postgresql://truthlens:truthlens@127.0.0.1:5433/truthlens_test"
python -m pytest -q
```

Unit tests cover retry classification, backoff, result validation and error codes.
Integration tests cover concurrent claims, `SKIP LOCKED`, lease recovery, fencing,
retry transitions, duplicate findings through the unique constraint, and full worker runs.

Current results (Stage 3 verification):

| Suite | Result |
| --- | --- |
| `backend` `npm test` | 5 passed |
| `ai-service` `pytest -q` | 43 passed |
| `backend` `npm run lint` | 0 problems |
| `frontend` `npx eslint .` | 0 problems |

## Local development (without Docker)

```bash
# backend
cd backend && npm install && npm run dev

# ai-service
cd ai-service && pip install -r requirements.txt
python -m uvicorn src.main:app --reload

# worker
cd ai-service && python -m src.worker.worker

# frontend
cd frontend && npm install && npm run dev
```

Frontend scripts pass `--webpack` because this environment cannot load the native SWC
binary. On a normal machine `next dev` / `next build` (Turbopack) can be used directly.

## Known environment issues

- `minio/minio` cannot be pulled in this environment (access denied, `quay.io` returns
  401). MinIO is optional and only needed once the S3 storage driver is implemented.
  Start it with `docker compose --profile s3 up -d`.
- Host port `5432` is occupied by another container here, so local runs use `POSTGRES_PORT=5433`.
- The native SWC binary is invalid on this machine; Next falls back to WebAssembly, so the
  frontend uses Webpack.
