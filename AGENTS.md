# AGENTS.md — OpenCode working instructions for TruthLens

This file is the single source of truth for how OpenCode (and any coding agent)
must work on the TruthLens repository. It complements, and must not contradict,
`README.md` and `docs/ARCHITECTURE.md`.

If a rule here conflicts with another file, stop and ask before proceeding.

---

## 1. Project identity

TruthLens is a Hebrew/RTL SaaS that analyses uploaded videos and reports
whether they look AI-generated or AI-edited. The product is built as
independently deployable services. The UI is Hebrew/RTL; future Android/iOS
support is planned.

Current stage: **Stage 3 — Database & Job Queue** (see `docs/STAGE3_REPORT.md`).
No Stage 4 work may start without explicit user approval.

## 2. Detected stack (do not invent alternatives)

Versions listed below use the ranges declared in `package.json` (with `^`). They are
not necessarily the exact versions installed; verify the resolved versions in the
corresponding lock file (`package-lock.json` / `requirements` pins) when precision matters.

| Area | Technology |
| --- | --- |
| Frontend | Next.js 16.4.5, React 19.3.1, TypeScript 5.9.3, ESLint 10 + `eslint-config-next` 16.4.5 |
| Backend | Node.js 22, Fastify 5.12.8, TypeScript, Prisma 6.19.3, ESLint 10 + `typescript-eslint` 8.72.1 |
| AI service | Python 3.12, FastAPI 0.115.0, Pydantic 2.9.2 |
| Worker | Python 3.12 process, `psycopg` 3.3.8 (raw SQL, `FOR UPDATE SKIP LOCKED`) |
| Database | PostgreSQL 16 |
| Storage | Local / S3-compatible (MinIO optional) — contract defined, upload API later |
| Orchestration | Docker Compose (services: frontend, backend, ai-service, worker, postgres, optional minio) |

Package managers: `npm` (frontend/backend), `pip` (ai-service/worker).
No monorepo tooling, no CI directory, no test runner beyond Node `node:test` and `pytest`.

## 3. Repository layout

```
truthlens/
├── frontend/          Next.js app (Hebrew/RTL shell)
├── backend/           Fastify API + Prisma schema/migrations
│   ├── prisma/        schema.prisma + migrations/
│   ├── src/           server, db, queue, routes
│   └── tests/         jobs.test.ts (Node test runner)
├── ai-service/        FastAPI (stateless; no DB access) + worker package
│   ├── src/main.py
│   ├── src/worker/    config, errors, backoff, queue, heartbeat, analysis, runner, worker
│   └── tests/         pytest unit + integration
├── docs/              ARCHITECTURE.md, STAGE3_REPORT.md
├── AGENTS.md          OpenCode working instructions (this file)
├── opencode.json      OpenCode MCP configuration (Atlassian)
├── docker-compose.yml
├── .env.example
└── README.md
```

Never create a second copy of an existing module. Extend existing files.

## 4. Jira workflow (mandatory)

- Jira site: `https://daniel213126.atlassian.net`, project `KAN`.
- Atlassian MCP is configured in `opencode.json`.
- Before starting any task:
  1. Read the full Jira issue description.
  2. Read all subtasks and dependencies (search `parent = <KEY>`).
  3. Check the existing code and documentation before creating anything.
- Execute **one subtask at a time**. Never implement a whole Epic or the backlog in one request.
- Do not invent technologies, libraries, filenames, or APIs. If information is missing,
  inspect the code and docs first.
- Preserve the existing stack and conventions. Architecture changes require justification and documentation.
- Write simple, focused, modular code. No giant files; no artificial splitting.
- Add or update tests for every change; keep existing tests aligned.
- Run relevant lint, tests, and build before finishing.
- Never mark a Jira issue `Done` if tests failed or acceptance criteria are unmet.
- At the end of every task write a summary: what changed, files changed, tests run and
  results, and what is blocked.
- Never commit or push without explicit user approval.
- Never expose secrets, private videos, or sensitive data in Git.

## 5. AI result honesty

TruthLens must never present an AI result as absolute proof. Use `inconclusive` when
evidence is insufficient. The Stage 3 worker uses `provider = "mock"` and must never be
presented to users as a real model verdict.

## 6. Service responsibility boundaries

| Service | Owns | Must not |
| --- | --- | --- |
| Frontend | Hebrew/RTL UI | Access DB, storage, or AI provider directly |
| Backend | Public API, job creation, reads results | Run analysis, write findings |
| AI service | Stateless analysis contract | Access DB or queue |
| Worker | Claim, lease, heartbeat, recovery, findings, retry | Expose HTTP, serve users, create uploads |
| Postgres | Source of truth + queue | — |

The AI service has no `DATABASE_URL` and no `depends_on: postgres`.

## 7. Run and test commands

Authoritative, up-to-date commands live in `README.md` (sections "Quick start", "Database", "Tests").
Do not duplicate them here; read them from README when needed.

Agent-critical notes:

- Default host port for PostgreSQL is **5433** (`POSTGRES_PORT`). In this development
  environment a native PostgreSQL 18 also listens on 5433, so verification used 5544.
- Migrations are **never** applied automatically on application start; run
  `npx prisma migrate deploy` explicitly.
- The native SWC binary is unusable here; Next.js runs with `--webpack`.
- MinIO is optional (`docker compose --profile s3 up -d`).

## 8. Key invariants (do not break)

- `findings` uniqueness is enforced by PostgreSQL (`UNIQUE (job_id, dedupe_key)`),
  not by transactions alone.
- Every worker write is fenced by `lease_token`.
- Retry budget is exactly 3 attempts (5 s, then 15 s, then failure).
- Non-transient errors are never retried.
- `Job.updatedAt` uses `@default(now()) @updatedAt` so raw SQL inserts work.
- Primary keys have a DB-level `gen_random_uuid()` default.
- Migrations are applied explicitly, never on application start.
- MinIO is optional (`--profile s3`).

## 9. Definition of done for a task

- Code changed is minimal and focused.
- Tests added/updated and passing.
- Relevant lint and build pass.
- README/docs updated if commands or behaviour changed.
- Summary written (changed files, tests, results, blockers).
- Jira issue not marked `Done` until all of the above hold.

## 10. References

- `README.md` — run, migrate, test instructions.
- `docs/ARCHITECTURE.md` — architecture, schema, queue protocol, storage consistency.
- `docs/STAGE3_REPORT.md` — Stage 3 implementation report and verification results.
- `docker-compose.yml` — service wiring and healthchecks.
- `.env.example` — environment variable contract.
