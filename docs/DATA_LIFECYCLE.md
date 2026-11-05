# TruthLens — Data Lifecycle & Privacy (KAN-16)

**Status:** Draft (KAN-16)
**Stage:** Product discovery / privacy & data lifecycle (Epic KAN-4)
**Complements:** `docs/PRODUCT_VISION.md`, `docs/ARCHITECTURE.md`, `docs/USER_JOURNEYS.md`, `docs/AI_PROVIDER_RESEARCH.md`, `docs/STAGE3_REPORT.md`
**Last updated:** 2026-11
**Language/UI:** Hebrew, RTL

## 1. Purpose

This document defines the TruthLens data lifecycle and privacy baseline in a short
form, as required by KAN-16 ("Data Lifecycle & Privacy" deliverable). It records what
information is retained, for what purpose, where it is stored, for how long, and how it
is deleted, and which questions remain open.

TruthLens must never present an AI result as absolute proof. `inconclusive` is used when
evidence is insufficient.

## 2. Information types

| # | Information type | Purpose | Storage location | Retention (current implementation) | Retention (proposed – pending) |
| --- | --- | --- | --- | --- | --- |
| 1 | Source file (video) | Analysis input | Object storage (`storageKey`, source filename / metadata in `jobs`) | Not yet in force for user uploads (Stage 3 has job creation via `enqueueJob` only; upload API pending) | **Pending Product Approval + Legal Review** (draft value pending) |
| 2 | Frames / thumbnails | Visual anchors for findings | Not produced in the current implementation | Not applicable | Not applicable / not implemented |
| 3 | Metadata | Provenance of the analysis | `jobs` (filename, content type, size) | Current | Pending |
| 4 | Result | Cautious verdict + findings (+ confidence / summary / limitations) | `jobs` / `findings` (persisted via worker, fenced) | Current (mock in Stage 3) | Pending (retained only as long as needed) |
| 5 | Check identifier | Job linkage | `jobs.id` | Current | Tied to job retention |
| 6 | Operational data | Reliability (worker liveness, errors, lease, attempts) | Postgres + worker logs | Current | Pending |

## 3. File & result lifecycle

Required lifecycle flow:

**Upload → Storage → Analysis → Result → Expiration → Deletion**

- **Upload / Storage:** source file is written (planned via `StorageDriver`: local default, S3/MinIO optional) and a `jobs` row is inserted (compensating actions defined in `docs/ARCHITECTURE.md` §7).
- **Analysis:** worker claims job, calls AI service, writes findings under lease fence.
- **Result:** job moves to `completed` with verdict/findings (contract verdicts per KAN-15).
- **Expiration:** source-file retention is a proposed MVP policy (pending approval).
- **Deletion:** manual and/or scheduled deletion paths are planned; current safety mechanisms include job→findings cascade, orphan janitor, and `OBJECT_MISSING` handling.

## 4. Retention policy (Proposed MVP Policy)

- Source files: retention duration is **Pending Product Approval + Legal Review**.
- Frames / thumbnails: not produced in the current implementation.
- Results: retention is proposed to be limited to product need (pending decision).

## 5. Deletion

- Manual user-initiated deletion (file + related job/findings records): **planned, not yet implemented** (must not be presented as existing).
- Automatic expiration / cleanup: **planned, not yet implemented** (no TTL mechanism added in this stage).
- Existing mechanisms: `jobs` deletion cascades to `findings`; janitor removes orphaned objects after grace period; `OBJECT_MISSING` marks jobs failed.

## 6. Data sent to AI providers

- The worker sends the storage reference / bytes (and job context) to the AI provider for analysis.
- Provider-side retention of such data is **unknown**; no commitment is made about provider behavior.
- Open questions: provider data retention, data residency, deletion on provider side.

## 7. Information security, permissions, encryption, logs

- Security principles: no secrets, private videos, or sensitive data in logs; worker logs are job-scoped operational data.
- Encryption / access control / temporary file access & deletion paths: planned for MVP (not yet implemented in code).

## 8. Legal review topics

Topics that require legal / privacy review before public launch (flagged; this document is **not** legal advice):
- AI provider data retention and data transfer.
- User consent and deletion rights.
- Retention periods.

## 9. Open items / pending approvals

- Retention durations (source files, results).
- MVP privacy policy scope and user deletion flow.
- AI provider retention answers.
- Legal review outcomes.

---

*Draft for KAN-16 (Data Lifecycle & Privacy); retention / policy pending product
approval and legal review.*
