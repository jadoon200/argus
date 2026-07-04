import json
from typing import Any

from argus.agent.state import EvidenceItem
from argus.eval.judge import judge_brief

_EV = [
    EvidenceItem(
        "reuters.com:1", "Naval patrols increase", "reuters.com", "B", 3, "Ships deployed."
    )
]


class JudgeFake:
    """Returns canned structured verdicts (cycled), so the judge runs with no model."""

    name = "judge-fake"

    def __init__(self, verdicts: list[dict[str, Any]]) -> None:
        self._verdicts = verdicts
        self._i = 0

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        verdict = self._verdicts[self._i % len(self._verdicts)]
        self._i += 1
        return json.dumps(verdict)


def test_judge_aggregates_faithfulness_and_support() -> None:
    backend = JudgeFake(
        [
            {"grounded": True, "supported": True, "reason": "cited item backs it"},
            {"grounded": True, "supported": False, "reason": "grounded but uncited"},
        ]
    )
    scores = judge_brief(["escalation likely [E1]", "vessels massed"], _EV, backend)
    assert scores.n == 2
    assert scores.faithfulness == 1.0  # both grounded
    assert scores.citation_support == 0.5  # only one had its citation support the claim


def test_judge_skips_unparseable_verdicts() -> None:
    class Bad:
        name = "bad"

        def complete(
            self,
            system: str,
            user: str,
            response_schema: dict[str, Any] | None = None,
            temperature: float | None = None,
        ) -> str:
            return "not json at all"

    scores = judge_brief(["a claim"], _EV, Bad())
    assert scores.n == 0  # a judge that fails to answer is skipped, not counted against the brief


def test_judge_ignores_blank_judgments() -> None:
    backend = JudgeFake([{"grounded": True, "supported": True}])
    scores = judge_brief(["", "   "], _EV, backend)
    assert scores.n == 0
