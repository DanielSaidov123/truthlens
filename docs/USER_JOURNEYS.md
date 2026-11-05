# TruthLens — User Journeys & Flows (KAN-12)

**Status:** Draft (KAN-12)  
**Stage:** Product discovery (Epic KAN-4)  
**Complements:** `docs/PRODUCT_VISION.md`, `docs/ARCHITECTURE.md`, `docs/MVP_SCOPE.md` (scope section in PRODUCT_VISION.md)  
**Language/UI:** Hebrew, RTL

This document maps user flows from input to result. It is documentation only:
it does not change product code and does not introduce new APIs.

---

## 1. Existing vs. planned capabilities

### Existing (implemented in Stage 3)

- Backend Fastify service with `GET /health` → `{ "status": "ok" }`.
- Backend Prisma helpers: `enqueueJob`, `getJobWithFindings` (not yet exposed as HTTP routes).
- PostgreSQL schema: `jobs`, `findings`, lease fencing, retry, idempotency.
- Worker: claims jobs, heartbeat, recovery, mock analysis (`provider = "mock"`),
  fenced completion/failure, retry 3 attempts (5 s / 15 s).
- AI service: `GET /health` only (stateless; no DB).
- Frontend: shell page only (`TruthLens` heading); no upload/result/status UI.

### Planned (Stage 4+; not implemented)

- Upload API and object storage write path.
- URL ingestion (link submission).
- Frontend flows: file selection, progress, result display.
- Real AI provider integration (worker currently uses mock).
- HTTP routes for job creation and result retrieval (backend helpers exist).

No endpoint paths, request/response shapes, or progress percentages are invented
here; unknowns are marked as **Open Question**.

---

## 2. Job state machine (single source of truth)

States are exactly the `JobStatus` enum in `backend/prisma/schema.prisma`:

```
queued ──claim──> processing ──complete──> completed
                      │
                      ├──fail (transient, attempts remain)──> queued
                      └──fail (permanent / budget exhausted)──> failed
```

- `queued`: waiting to be claimed; `next_attempt_at` controls eligibility.
- `processing`: claimed by a worker holding a `lease_token`; heartbeat extends lease.
- `completed`: result written under the fencing token.
- `failed`: terminal; `error_code` / `error_message` set.

Rules (from `docs/ARCHITECTURE.md`):

- There is **no progress percentage** in the job model. The frontend must not
  invent or display unsupported progress values.
- Status is the only progress signal available in Stage 3.
- `provider = "mock"` must never be presented as a real model verdict.

---

## 3. Journey A — Upload a file (planned)

> Upload API is not implemented in Stage 3. This flow describes the intended
> MVP behaviour and the parts that already exist.

| Step | User action | Frontend (what user sees) | Backend request / response | Worker / DB | Success | Failure |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Opens the app | Homepage (Hebrew/RTL) | — | — | — | — |
| 2 | Selects a local video file | File picker / validation feedback | — | — | Accepted file type/size | Rejected: unsupported type or too large (message shown) |
| 3 | Submits the file | "Submitting…" state | Job creation request (endpoint TBD) | `enqueueJob` inserts `queued` job | Returns job id | Validation error; no job created |
| 4 | Waits | Status view (queued/processing) | Status read (endpoint TBD) | Worker claims job (`processing`), heartbeat | Status updates to `processing` | Lease expiry → recovery; job returns to `queued` or `failed` |
| 5 | Analysis runs | Status view | — | Mock analysis (Stage 3) → fenced complete | Job becomes `completed` | Transient → requeue (5 s / 15 s); permanent → `failed` |
| 6 | Views result | Result screen | Result read (endpoint TBD) | `getJobWithFindings` | Verdict, findings, limitations, timestamps | `failed` → error code/message shown |

Notes:
- In Stage 3, jobs can be created directly in the DB (as in tests) to exercise
  the worker; there is no HTTP upload path.
- Confidence is shown only when grounded; otherwise omitted.

---

## 4. Journey B — Submit a link (planned)

> URL ingestion is not implemented in Stage 3.

| Step | User action | Frontend (what user sees) | Backend request / response | Worker / DB | Success | Failure |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Opens the app | Homepage | — | — | — | — |
| 2 | Enters a URL | Input + validation feedback | — | — | Supported source | Unsupported/private link → message |
| 3 | Submits the link | "Submitting…" state | Job creation request (endpoint TBD) | `enqueueJob` inserts `queued` job with `storage_key`/source ref | Returns job id | Validation error; no job created |
| 4 | Waits | Status view | Status read (endpoint TBD) | Worker claims and processes | Status `processing` → `completed` | As in Journey A |
| 5 | Views result | Result screen | Result read (endpoint TBD) | Findings returned | Verdict + findings + limitations | `failed` → error shown |

Open Question: exact URL validation rules and supported sources are not defined
(KAN-11/KAN-12 scope; to be specified in Stage 4).

---

## 5. View result

When a job reaches `completed` (fields from `jobs` / `findings` in Prisma schema):

- Frontend displays (existing schema fields; verdicts per the KAN-15 result contract):
  - `status`, `verdict` (`likely_ai_generated` / `possible_ai_edit` / `no_clear_ai_evidence` /
    `inconclusive`), `provider`, `model`.
  - Findings: `type`, `startSec`, `endSec`, `description`, `confidence` (only when
    grounded), `severity`, `evidence`.
  - Timestamps: `startedAt`, `completedAt`; result-level `analyzedAt` reuses `completedAt`.
- If verdict is `inconclusive` or `no_clear_ai_evidence`, the UI must state clearly that
  evidence was insufficient (no absolute claim).
- If `provider = "mock"`, the result must never be presented as a real model
  verdict (Stage 3 only).
- `summary` and `limitations` are result/DTO-level fields defined by the KAN-15 result
  contract and are not persisted in this stage.

Persisted mapping (KAN-15): `likely_ai_generated → ai_generated`, `possible_ai_edit → ai_edited`,
`no_clear_ai_evidence → likely_real`, `inconclusive → inconclusive`. The mapping is a
backward compatibility adaptation for the storage layer, not a claim of absolute certainty.

When a job is `failed`:

- Frontend displays `error_code` and a user-friendly message; no partial result.

---

## 6. Edge cases, error UX and recovery

### Error UX (detailed)

| Situation | Cause (existing vs. planned) | What the user sees | User action | Retryable? |
| --- | --- | --- | --- | --- |
| Unsupported file type | Planned validation (not implemented) | Validation error message naming the unsupported type | Choose a supported file type | No (input issue); resubmit with valid file |
| File too large | Planned validation (limit not defined) | Validation error message with size limit | Choose a smaller file | No (input issue); resubmit with valid file |
| Private / unsupported link | Planned validation (sources not defined) | Validation error naming the unsupported source | Provide a supported public URL | No (input issue); resubmit with valid URL |
| Provider / AI error | Planned (Stage 4); worker fails job | `error_code` + user-friendly message | Retry later or contact support | Transient: yes (worker retries 3×); permanent: no |
| HTTP request timeout | Planned (no HTTP job API yet) | TBD (no endpoint exists) | TBD | N/A (planned) |
| AI provider timeout | Planned (Stage 4); worker classifies `TimeoutError` as transient | Status reflects retry; final `failed` with `TIMEOUT` | Resubmit after the provider recovers | Yes (worker retries 5 s / 15 s, then `failed`) |
| Lease expired | Existing (`recover_expired`) | Job retried or marked `failed` with `LEASE_EXPIRED` | None (automatic); resubmit if `failed` | Automatic requeue if retry budget remains |
| Duplicate submission | Findings dedup implemented; job-level dedup **not** implemented (Open Question) | No duplicate findings; job may be created twice | None | N/A |
| Crash during processing | Existing (lease expiry → recovery) | Job retried or marked `failed` | None (automatic); resubmit if `failed` | Automatic requeue if budget remains |
| Missing object in storage | Planned (error code `OBJECT_MISSING` defined in worker) | Error message with `OBJECT_MISSING` | Resubmit the file | No (permanent) |

### Idempotency

- **Findings dedup (implemented):** `UNIQUE (job_id, dedupe_key)` in PostgreSQL plus
  `ON CONFLICT (job_id, dedupe_key) DO NOTHING` in `complete_job`. The worker derives
  `dedupe_key` and falls back to `code:startSec:endSec`. Replay cannot create
  duplicates.
- **Job dedup (not implemented):** there is no unique constraint or dedup logic at
  the job level (e.g. by `storage_key` or request id). Creating the same job twice
  creates two jobs. **Open Question:** whether job-level idempotency is needed and
  how to key it.

### Timeouts (existing vs. planned)

- **HTTP request timeout:** not applicable in Stage 3 (no HTTP job API). Planned.
- **AI provider timeout:** not applicable in Stage 3 (mock analysis has no network
  call). Planned for Stage 4; worker will classify `TimeoutError` as transient.
- **Lease expiration:** implemented. Heartbeat extends `lease_expires_at`; expired
  leases are recovered by `recover_expired` (requeue or `LEASE_EXPIRED`).

Recovery is driven by `recover_expired` in `ai-service/src/worker/queue.py` and the
worker loop; no manual intervention is required for lease expiry.

---

## 7. Open questions

1. Exact HTTP endpoints and request/response shapes for job creation and result
   read (backend helpers exist; routes not implemented).
2. Supported file types and size limits.
3. Supported URL sources and validation rules.
4. Whether to track abandonment rate (requires measuring started analyses that
   never reach a terminal status).
5. Whether to show any progress indicator beyond status (no percentage exists
   in the job model).
6. Authentication and per-user history (out of MVP scope per KAN-11).

---

## 8. References

- `docs/PRODUCT_VISION.md` — vision, use cases, KPIs, scope (KAN-10/KAN-11).
- `docs/ARCHITECTURE.md` — services, schema, queue protocol, storage consistency.
- `docs/STAGE3_REPORT.md` — Stage 3 implementation and verification.
- `AGENTS.md` — working instructions.
- Jira: Epic `KAN-4`, tasks `KAN-10`, `KAN-11`, `KAN-12`.

---

*This document is a living draft. Changes require a Jira task and must not
contradict `ARCHITECTURE.md`.*