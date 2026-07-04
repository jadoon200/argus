import json
from typing import Any

from argus.agent.assurance import assured_confidence, calibrate


def test_calibrate_unanimous_keeps_confidence() -> None:
    assert calibrate(["high", "high", "high"]) == ("high", 1.0)


def test_calibrate_keeps_at_two_thirds_agreement() -> None:
    assert calibrate(["moderate", "moderate", "low"]) == ("moderate", 0.67)


def test_calibrate_downgrades_when_the_panel_wobbles() -> None:
    # one of each → modal (first-seen) is high at only 1/3 agreement → downgraded to moderate
    assert calibrate(["high", "moderate", "low"]) == ("moderate", 0.33)


def test_calibrate_low_cannot_go_lower() -> None:
    assert calibrate(["low", "moderate", "high"]) == ("low", 0.33)


def test_calibrate_empty_is_low() -> None:
    assert calibrate([]) == ("low", 0.0)


class SeqAdjudicator:
    """Returns adjudicator findings with a cycling confidence, so self-consistency can vary."""

    name = "seq"

    def __init__(self, confidences: list[str]) -> None:
        self._confidences = confidences
        self._i = 0

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        conf = self._confidences[self._i % len(self._confidences)]
        self._i += 1
        return json.dumps(
            {"key_judgments": [{"judgment": "x", "citations": ["E1"]}], "confidence": conf}
        )


def test_assured_confidence_samples_and_calibrates() -> None:
    state = {"query": "q", "evidence": [], "hypotheses": ["H1"], "critiques": []}
    conf, agreement = assured_confidence(
        state, SeqAdjudicator(["high", "moderate", "low"]), samples=3, temperature=0.4
    )
    assert conf == "moderate" and agreement == 0.33  # wobbly panel -> downgraded from high
