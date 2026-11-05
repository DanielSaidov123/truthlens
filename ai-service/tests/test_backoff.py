from src.worker.backoff import retry_delay


def test_first_failure_waits_five_seconds():
    assert retry_delay(1) == 5


def test_second_failure_waits_fifteen_seconds():
    assert retry_delay(2) == 15


def test_third_failure_has_no_retry():
    assert retry_delay(3) is None
    assert retry_delay(4) is None


def test_zero_attempts_maps_to_first_delay():
    assert retry_delay(0) == 5
