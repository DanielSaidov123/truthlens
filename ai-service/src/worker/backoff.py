"""Retry schedule.

Policy: at most 3 attempts in total.
- attempt 1 fails -> wait 5 seconds -> attempt 2
- attempt 2 fails -> wait 15 seconds -> attempt 3
- attempt 3 fails -> failed, no further wait

``retry_delay`` receives the number of attempts already made (the value stored
on the job after claiming) and returns the delay before the next attempt, or
``None`` when the budget is exhausted.
"""

from __future__ import annotations

BACKOFF_SECONDS: tuple[int, ...] = (5, 15)


def retry_delay(attempts_made: int) -> int | None:
    if attempts_made < 1:
        return BACKOFF_SECONDS[0]
    if attempts_made > len(BACKOFF_SECONDS):
        return None
    return BACKOFF_SECONDS[attempts_made - 1]
