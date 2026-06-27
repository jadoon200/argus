"""The optimization metric — the same honesty bar the eval enforces.

Reward citation coverage, but zero it out if the brief overstates confidence past the
gold cap (the calibration discipline). So DSPy optimizes toward *cited and calibrated*
briefs, not merely fluent ones — the eval literally drives the agent.
"""

from typing import Any

from argus.eval.metrics import citation_coverage, exceeds_confidence


def brief_metric(example: Any, prediction: Any, trace: Any = None) -> float:
    judgments = list(getattr(prediction, "key_judgments", []) or [])
    coverage = citation_coverage([str(j) for j in judgments])
    confidence = str(getattr(prediction, "confidence", "") or "").strip().lower()
    cap = getattr(example, "max_confidence", None)
    if exceeds_confidence(confidence, cap):
        return 0.0
    return coverage
