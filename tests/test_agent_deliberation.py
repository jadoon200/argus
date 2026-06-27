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

    def complete(self, system: str, user: str) -> str:
        # Match the unique ROLE: markers (the Adjudicator prompt also mentions
        # "Red Team" and "Analyst", so plain substring checks would collide).
        if "ROLE: Hypothesis-setter" in system:
            return "H1: The activity is escalation.\nH2: The activity is routine."
        if "ROLE: Lead Analyst" in system:
            return "I favour H1; the patrols [E1] indicate escalation."
        if "ROLE: Red Team" in system:
            return "Over-reliant on a single source [E1]; H2 is plausible [E2]."
        if "ROLE: Adjudicator" in system:
            return (
                "KEY JUDGMENTS:\n"
                "- Escalation is likely given the deployment [E1].\n"
                "CONFIDENCE: moderate - limited corroboration.\n"
                "ALTERNATIVES: H2 routine activity; more independent sources would raise it.\n"
                "INTELLIGENCE GAPS: intentions are unknown [E9]."  # [E9] is out of range
            )
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
