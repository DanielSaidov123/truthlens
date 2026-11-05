import pytest

from src.worker.errors import PermanentError
from src.worker.runner import validate_result


def valid_result():
    return {
        "verdict": "inconclusive",
        "provider": "mock",
        "model": "stage3-mock-v1",
        "findings": [
            {
                "type": "MOCK_FINDING",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "description": "Mock",
                "confidence": None,
                "evidence": {"mock": True},
                "severity": "info",
            }
        ],
    }


def test_valid_result_is_accepted():
    verdict, findings, provider, model = validate_result(valid_result())
    assert verdict == "inconclusive"
    assert len(findings) == 1
    assert findings[0].type == "MOCK_FINDING"
    assert provider == "mock"
    assert model == "stage3-mock-v1"


@pytest.mark.parametrize(
    "verdict",
    [
        "likely_ai_generated",
        "possible_ai_edit",
        "no_clear_ai_evidence",
        "inconclusive",
    ],
)
def test_all_contract_verdicts_are_accepted(verdict):
    result = valid_result()
    result["verdict"] = verdict
    validated_verdict, findings, provider, _model = validate_result(result)
    assert validated_verdict == verdict
    assert len(findings) == 1
    assert provider == "mock"


@pytest.mark.parametrize(
    "verdict",
    ["real", "fake", "", None, "ai_generated", "ai_edited", "likely_real"],
)
def test_invalid_verdict_is_rejected(verdict):
    result = valid_result()
    result["verdict"] = verdict
    with pytest.raises(PermanentError):
        validate_result(result)


def test_missing_provider_is_rejected():
    result = valid_result()
    result.pop("provider")
    with pytest.raises(PermanentError):
        validate_result(result)


def test_start_after_end_is_rejected():
    result = valid_result()
    result["findings"][0]["end_sec"] = -1.0
    with pytest.raises(PermanentError):
        validate_result(result)


def test_findings_must_be_a_list():
    result = valid_result()
    result["findings"] = {"code": "x"}
    with pytest.raises(PermanentError):
        validate_result(result)


def test_contract_verdicts_map_to_persisted_verdicts():
    from src.contract import PERSISTED_VERDICTS, PERSISTED_VERDICT_MAP, RESULT_VERDICTS, to_persisted_verdict

    assert set(RESULT_VERDICTS) == {
        "likely_ai_generated",
        "possible_ai_edit",
        "no_clear_ai_evidence",
        "inconclusive",
    }
    assert set(PERSISTED_VERDICTS) == {"ai_generated", "ai_edited", "likely_real", "inconclusive"}
    assert PERSISTED_VERDICT_MAP["likely_ai_generated"] == "ai_generated"
    assert PERSISTED_VERDICT_MAP["possible_ai_edit"] == "ai_edited"
    assert PERSISTED_VERDICT_MAP["no_clear_ai_evidence"] == "likely_real"
    assert PERSISTED_VERDICT_MAP["inconclusive"] == "inconclusive"


def test_unknown_contract_verdict_cannot_be_persisted():
    from src.contract import to_persisted_verdict

    with pytest.raises(ValueError):
        to_persisted_verdict("probably_fake")
