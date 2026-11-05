-- CreateEnum
CREATE TYPE "JobStatus" AS ENUM ('queued', 'processing', 'completed', 'failed');

-- CreateEnum
CREATE TYPE "Verdict" AS ENUM ('ai_generated', 'ai_edited', 'likely_real', 'inconclusive');

-- CreateTable
CREATE TABLE "jobs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "status" "JobStatus" NOT NULL DEFAULT 'queued',
    "verdict" "Verdict",
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "max_attempts" INTEGER NOT NULL DEFAULT 3,
    "next_attempt_at" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "lease_token" UUID,
    "lease_expires_at" TIMESTAMPTZ(3),
    "last_heartbeat_at" TIMESTAMPTZ(3),
    "error_code" TEXT,
    "error_message" TEXT,
    "storage_key" TEXT,
    "original_filename" TEXT,
    "content_type" TEXT,
    "size_bytes" BIGINT,
    "provider" TEXT,
    "model" TEXT,
    "created_at" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" TIMESTAMPTZ(3),
    "completed_at" TIMESTAMPTZ(3),

    CONSTRAINT "jobs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "findings" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "job_id" UUID NOT NULL,
    "dedupe_key" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT,
    "start_sec" DOUBLE PRECISION NOT NULL,
    "end_sec" DOUBLE PRECISION NOT NULL,
    "confidence" DOUBLE PRECISION,
    "severity" TEXT,
    "evidence" JSONB,
    "created_at" TIMESTAMPTZ(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "findings_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "jobs_status_next_attempt_at_idx" ON "jobs"("status", "next_attempt_at");

-- CreateIndex
CREATE INDEX "jobs_status_lease_expires_at_idx" ON "jobs"("status", "lease_expires_at");

-- CreateIndex
CREATE INDEX "jobs_created_at_idx" ON "jobs"("created_at");

-- CreateIndex
CREATE INDEX "findings_job_id_idx" ON "findings"("job_id");

-- CreateIndex
CREATE UNIQUE INDEX "findings_job_id_dedupe_key_key" ON "findings"("job_id", "dedupe_key");

-- AddForeignKey
ALTER TABLE "findings" ADD CONSTRAINT "findings_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "jobs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
