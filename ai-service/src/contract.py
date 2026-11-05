"""Provider-independent analysis result contract (KAN-15).

Central definition of the analysis result shared by the AI service, worker and the
backend DTO layer. Verdicts use cautious semantics: ``likely_ai_generated`` /
``possible_ai_edit`` for probable AI generation/editing, ``no_clear_ai_evidence``
when the evidence is weak, and ``inconclusive`` when the analysis cannot support a
claim.

Contract verdicts are mapped to the persisted ``Verdict`` enum values kept in
``backend/prisma/schema.prisma`` (``ai_generated``, ``ai_edited``, ``likely_real``,
``inconclusive``) via :data:`PERSISTED_VERDICT_MAP`. The mapping is a backward
compatibility adaptation for the storage layer, not a claim of absolute certainty.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

RESULT_VERDICTS: tuple[str, ...] = (
    "likely_ai_generated",
    "possible_ai_edit",
    "no_clear_ai_evidence",
    "inconclusive",
)

PERSISTED_VERDICTS: tuple[str, ...] = (
    "ai_generated",
    "ai_edited",
    "likely_real",
    "inconclusive",
)

PERSISTED_VERDICT_MAP: dict[str, str] = {
    "likely_ai_generated": "ai_generated",
    "possible_ai_edit": "ai_edited",
    "no_clear_ai_evidence": "likely_real",
    "inconclusive": "inconclusive",
}


def to_persisted_verdict(contract_verdict: str) -> str:
    """Map a contract verdict to the persisted ``Verdict`` enum value."""
    persisted = PERSISTED_VERDICT_MAP.get(contract_verdict)
    if persisted is None:
        raise ValueError(f"Unknown contract verdict: {contract_verdict!r}")
    return persisted


class Finding(BaseModel):
    """A single evidence-backed finding with a time range."""

    type: str = Field(..., description="Finding category, e.g. temporal_inconsistency")
    start_sec: float = Field(..., description="Start of the suspicious segment, in seconds from the video start")
    end_sec: float = Field(..., description="End of the suspicious segment, in seconds from the video start")
    description: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, Any] | None = None
    severity: str | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "Finding":
        if self.start_sec > self.end_sec:
            raise ValueError("Finding start_sec must not be after end_sec")
        return self


class AnalysisResult(BaseModel):
    """The provider-independent analysis result contract."""

    verdict: str = Field(..., description="Cautious verdict: likely_ai_generated, possible_ai_edit, no_clear_ai_evidence or inconclusive")
    confidence: float | None = Field(default=None, ge=0, le=1, description="Calibrated confidence in [0, 1]; None when no calibrated score exists")
    summary: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    analyzed_at: datetime | None = None
    provider: str = Field(..., description="Provider identifier; 'mock' must never be presented as a real model verdict")
    model: str | None = None

    @field_validator("verdict")
    @classmethod
    def _verdict_is_known(cls, value: str) -> str:
        if value not in RESULT_VERDICTS:
            raise ValueError(f"Unknown verdict: {value!r}")
        return value
