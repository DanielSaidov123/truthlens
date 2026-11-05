import assert from "node:assert/strict";
import { after, beforeEach, test } from "node:test";

import { prisma } from "../src/db/prisma";
import { enqueueJob, getJobWithFindings } from "../src/queue/jobs";

beforeEach(async () => {
  await prisma.finding.deleteMany();
  await prisma.job.deleteMany();
});

after(async () => {
  await prisma.$disconnect();
});

test("enqueueJob creates a queued job with the default retry budget", async () => {
  const before = Date.now();
  const job = await enqueueJob({
    storageKey: "analyses/demo/video.mp4",
    originalFilename: "video.mp4",
    contentType: "video/mp4",
    sizeBytes: 1234n,
  });

  assert.equal(job.status, "queued");
  assert.equal(job.attempts, 0);
  assert.equal(job.maxAttempts, 3);
  assert.equal(job.leaseToken, null);
  assert.ok(job.nextAttemptAt.getTime() <= before + 1000);
  assert.equal(job.storageKey, "analyses/demo/video.mp4");
});

test("getJobWithFindings returns findings ordered by time", async () => {
  const job = await enqueueJob();

  await prisma.finding.createMany({
    data: [
      {
        jobId: job.id,
        dedupeKey: "late",
        code: "LATE",
        title: "Late",
        startSec: 5,
        endSec: 6,
      },
      {
        jobId: job.id,
        dedupeKey: "early",
        code: "EARLY",
        title: "Early",
        startSec: 1,
        endSec: 2,
      },
    ],
  });

  const result = await getJobWithFindings(job.id);

  assert.ok(result);
  assert.deepEqual(
    result.findings.map((finding) => finding.code),
    ["EARLY", "LATE"],
  );
});

test("getJobWithFindings returns null for an unknown id", async () => {
  assert.equal(
    await getJobWithFindings("00000000-0000-0000-0000-000000000000"),
    null,
  );
});

test("the database rejects duplicate findings for the same job", async () => {
  const job = await enqueueJob();
  const finding = {
    jobId: job.id,
    dedupeKey: "same-key",
    code: "DUP",
    title: "Duplicate",
    startSec: 0,
    endSec: 1,
  };

  await prisma.finding.create({ data: finding });

  await assert.rejects(() => prisma.finding.create({ data: finding }));
  assert.equal(await prisma.finding.count({ where: { jobId: job.id } }), 1);
});

test("deleting a job cascades to its findings", async () => {
  const job = await enqueueJob();
  await prisma.finding.create({
    data: {
      jobId: job.id,
      dedupeKey: "cascade",
      code: "CASCADE",
      title: "Cascade",
      startSec: 0,
      endSec: 1,
    },
  });

  await prisma.job.delete({ where: { id: job.id } });

  assert.equal(await prisma.finding.count(), 0);
});
