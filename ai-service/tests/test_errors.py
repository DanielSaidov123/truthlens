from src.worker.errors import (
    PermanentError,
    TransientError,
    error_code,
    is_transient,
)


def test_transient_errors_are_retryable():
    assert is_transient(TransientError("network")) is True
    assert is_transient(TimeoutError("slow")) is True
    assert is_transient(ConnectionError("refused")) is True


def test_permanent_errors_are_not_retryable():
    assert is_transient(PermanentError("bad media")) is False
    assert is_transient(ValueError("malformed")) is False
    assert is_transient(FileNotFoundError("missing object")) is False


def test_error_codes_are_stable():
    assert error_code(TransientError("x")) == "TRANSIENT_ERROR"
    assert error_code(PermanentError("x")) == "PERMANENT_ERROR"
    assert error_code(FileNotFoundError("x")) == "OBJECT_MISSING"
    assert error_code(TimeoutError("x")) == "TIMEOUT"
    assert error_code(ConnectionError("x")) == "CONNECTION_ERROR"
    assert error_code(ValueError("x")) == "INTERNAL_ERROR"
