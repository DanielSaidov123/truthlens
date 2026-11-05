# TruthLens

## Stage 2 – Scaffolding (current)

This stage contains only the project skeleton. No product logic, no AI provider, no URL ingestion, no auth/billing,
no database schema and no storage implementation yet.

### Services

| Service      | Stack                          | Host port   | Purpose                                      |
| ------------ | ------------------------------ | ----------- | -------------------------------------------- |
| `frontend`   | Next.js (App Router) + TS      | `3000`      | Hebrew/RTL web UI shell                      |
| `backend`    | Node.js + Fastify + TS         | `3001`      | Public API (`/health` only for now)          |
| `ai-service` | Python 3.12 + FastAPI          | `8000`      | Analysis service API (`/health` only for now)|
| `worker`     | Python worker process          | internal    | Long-running job runner (placeholder)        |
| `postgres`   | PostgreSQL 16                  | `5433`\*    | Primary datastore                            |
| `minio`      | MinIO                          | `9000/9001` | Local object storage (see known issues)      |

\* Host port is configurable with `POSTGRES_PORT`; it defaults to `5432`.

### Quick start

```bash
cp .env.example .env
docker compose up -d --build
```

If host port `5432` is already taken:

```powershell
$env:POSTGRES_PORT=5433; docker compose up -d --build
```

### Health endpoints (skeleton)

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:3001/health` → `{"status":"ok"}`
- AI Service: `http://localhost:8000/health` → `{"status":"ok"}`

### Local development (without Docker)

```bash
# backend
cd backend && npm install && npm run dev

# ai-service
cd ai-service && pip install -r requirements.txt
python -m uvicorn src.main:app --reload

# worker
cd ai-service && python src/worker/worker.py

# frontend
cd frontend && npm install && npm run dev
```

The frontend scripts pass `--webpack` because this environment cannot load the native SWC binary.
On a normal machine `next dev` / `next build` (Turbopack) can be used directly.

### Known environment issues

- `minio/minio` cannot be pulled from this environment's Docker registry (access denied / 401 on `quay.io`).
  The service stays defined in Compose but is not running locally.
- Host port `5432` is occupied by another container, so local runs use `POSTGRES_PORT=5433`.
