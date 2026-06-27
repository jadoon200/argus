import json
from typing import Any

from argus.agent.analyst import extractive_brief, generate_brief
from argus.agent.graph import run_deliberation
from argus.agent.state import EvidenceItem

_EVIDENCE = [
    EvidenceItem(
        "reuters.com:1", "Naval patrols increase", "reuters.com", "B", 3, "Ships deployed."
    ),
    EvidenceItem("rt.com:9", "Drills are routine", "rt.com", "D", 4, "State outlet claims."),
]


class FakeBackend:
    """Role-aware canned backend so the deliberation runs with no model/network."""

    name = "fake"

    def complete(
        self, system: str, user: str, response_schema: dict[str, Any] | None = None
    ) -> str:
        # Match the unique ROLE: markers (the Adjudicator prompt also mentions
        # "Red Team" and "Analyst", so plain substring checks would collide).
        if "ROLE: Hypothesis-setter" in system:
            if response_schema is not None:  # structured-output path
                return json.dumps(
                    {"hypotheses": ["The activity is escalation.", "The activity is routine."]}
                )
            return "H1: The activity is escalation.\nH2: The activity is routine."
        if "ROLE: Lead Analyst" in system:
            return "I favour H1; the patrols [E1] indicate escalation."
        if "ROLE: Red Team" in system:
            return "Over-reliant on a single source [E1]; H2 is plausible [E2]."
        if "ROLE: Adjudicator" in system:
            if response_schema is not None:
                return json.dumps(
                    {
                        # [E9] is out of range and must be dropped on resolution.
                        "key_judgments": [
                            {"judgment": "Escalation is likely", "citations": ["E1", "E9"]}
                        ],
                        "confidence": "moderate",
                        "confidence_rationale": "limited corroboration",
                        "alternative_hypothesis": "H2 routine activity is plausible",
                        "collection_requirement": "more independent sources",
                        "intelligence_gaps": ["intentions are unknown"],
                    }
                )
            return "KEY JUDGMENTS:\n- Escalation is likely [E1].\nCONFIDENCE: moderate."
        return ""


def test_deliberation_visits_all_roles() -> None:
    state = run_deliberation("q?", _EVIDENCE, FakeBackend(), debate_rounds=1)
    assert len(state["hypotheses"]) == 2
    assert state["analyst"]
    assert len(state["critiques"]) == 1
    assert state["finding"].startswith("KEY JUDGMENTS")
    roles = [role for role, _ in state["transcript"]]
    assert roles == ["hypotheses", "analyst", "red_team", "adjudicator"]


def test_debate_rounds_add_exchanges() -> None:
    state = run_deliberation("q?", _EVIDENCE, FakeBackend(), debate_rounds=2)
    assert len(state["critiques"]) == 2
    roles = [role for role, _ in state["transcript"]]
    assert roles == ["hypotheses", "analyst", "red_team", "analyst", "red_team", "adjudicator"]


def test_generate_brief_assembles_and_validates_citations() -> None:
    result = generate_brief("q?", evidence=_EVIDENCE, backend=FakeBackend(), persist=False)
    assert result.backend == "fake"
    assert result.confidence == "moderate"
    assert result.key_judgments  # parsed from KEY JUDGMENTS section
    assert result.hypotheses == ["The activity is escalation.", "The activity is routine."]
    # The fabricated [fabricated:99] citation is dropped; only the real id survives.
    assert result.citations == ["reuters.com:1"]
    assert result.alternatives and "routine" in result.alternatives
    assert result.gaps and "intentions" in result.gaps.lower()


def test_template_fallback_is_labelled_digest() -> None:
    result = extractive_brief("q?", _EVIDENCE)
    assert result.backend == "template"
    assert result.citations == ["reuters.com:1", "rt.com:9"]
    assert result.gaps and "deterministic fallback" in result.gaps


class NoJsonBackend:
    """Never returns valid JSON, even when a schema is requested — exercises the
    graceful fallback from the structured path to free-form text parsing."""

    name = "nojson"

    def complete(
        self, system: str, user: str, response_schema: dict[str, Any] | None = None
    ) -> str:
        if "ROLE: Hypothesis-setter" in system:
            return "H1: One.\nH2: Two."
        if "ROLE: Adjudicator" in system:
            return (
                "KEY JUDGMENTS:\n- Escalation is likely [E1].\n"
                "CONFIDENCE: high - well corroborated.\n"
                "ALTERNATIVES: routine activity.\nINTELLIGENCE GAPS: intentions unknown."
            )
        return "argument citing [E1]"


def test_structured_output_falls_back_to_text() -> None:
    result = generate_brief("q?", evidence=_EVIDENCE, backend=NoJsonBackend(), persist=False)
    assert result.backend == "nojson"
    assert result.confidence == "high"  # parsed from the free-form text path
    assert result.hypotheses == ["One.", "Two."]
    assert result.citations == ["reuters.com:1"]
