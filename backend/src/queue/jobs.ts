import type { Job } from "@prisma/client";

import { prisma } from "../db/prisma";

export interface CreateJobInput {
  storageKey?: string;
  originalFilename?: string;
  contentType?: string;
  sizeBytes?: bigint;
  maxAttempts?: number;
}

/**
 * Backend-owned write: create a queued job.
 * The worker is the only component that claims jobs or writes findings.
 */
export async function enqueueJob(input: CreateJobInput = {}): Promise<Job> {
  return prisma.job.create({
    data: {
      storageKey: input.storageKey,
      originalFilename: input.originalFilename,
      contentType: input.contentType,
      sizeBytes: input.sizeBytes,
      maxAttempts: input.maxAttempts ?? 3,
    },
  });
}

/** Backend-owned read used by the future API layer. */
export async function getJobWithFindings(jobId: string) {
  return prisma.job.findUnique({
    where: { id: jobId },
    include: {
      findings: {
        orderBy: [{ startSec: "asc" }, { endSec: "asc" }],
      },
    },
  });
}
