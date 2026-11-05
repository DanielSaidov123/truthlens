"""Job failure classification.

Transient failures may be retried. Permanent failures never are.
The classification is intentionally explicit so it can be unit-tested.
"""

from __future__ import annotations


class AnalysisError(Exception):
    """Base class for analysis failures with a stable error code."""

    code = "ANALYSIS_ERROR"
    transient = False

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class TransientError(AnalysisError):
    """Temporary failure: network hiccup, dependency unavailable, timeout."""

    code = "TRANSIENT_ERROR"
    transient = True


class PermanentError(AnalysisError):
    """Permanent failure: invalid media, malformed provider response, bad input."""

    code = "PERMANENT_ERROR"
    transient = False


def is_transient(exc: BaseException) -> bool:
    """Return True when an unexpected exception is safe to retry."""
    if isinstance(exc, AnalysisError):
        return exc.transient
    # A missing object is a permanent input problem, not a network hiccup.
    if isinstance(exc, FileNotFoundError):
        return False
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def error_code(exc: BaseException, fallback: str = "INTERNAL_ERROR") -> str:
    if isinstance(exc, AnalysisError):
        return exc.code
    if isinstance(exc, FileNotFoundError):
        return "OBJECT_MISSING"
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, ConnectionError):
        return "CONNECTION_ERROR"
    return fallback
