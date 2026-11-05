"""Deterministic mock analysis used until a real provider is approved.

It is explicitly marked as ``mock`` and must never be presented to users as a
real model verdict. The AI provider integration belongs to a later stage.

The returned payload follows the provider-independent result contract defined in
``src/contract.py`` (KAN-15). Verdicts are cautious; the mock uses
``inconclusive`` because no real model was executed.
"""

from __future__ import annotations

from typing import Any

from .queue import ClaimedJob


def mock_analyze(job: ClaimedJob) -> dict[str, Any]:
    return {
        "verdict": "inconclusive",
        "confidence": None,
        "summary": "Mock summary (not a real analysis)",
        "findings": [
            {
                "type": "MOCK_FINDING",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "description": (
                    "Placeholder produced by the Stage 3 worker. "
                    "No real model was executed."
                ),
                "confidence": None,
                "evidence": {"mock": True},
                "severity": "info",
            }
        ],
        "limitations": [
            "Mock analysis only; no real AI provider was executed."
        ],
        "analyzed_at": None,
        "provider": "mock",
        "model": "stage3-mock-v1",
    }
