"""TruthLens AI Service - Python Worker (skeleton only)."""

import asyncio


async def run_job(job_id: str) -> dict:
    """Placeholder for job execution. Stage 2 only."""
    return {"status": "completed", "jobId": job_id}


async def main() -> None:
    """Worker entrypoint placeholder: stays alive until stopped."""
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
