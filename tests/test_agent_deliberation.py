import json
from typing import Any

import pytest

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
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        # Match the unique ROLE: markers (the Adjudicator prompt also mentions
        # "Red Team" and "Analyst", so plain substring checks would collide).
        if "ROLE: Hypothesis-setter" in system:
            if response_schema is not None:  # structured-output path
                return json.dumps(
                    {"hypotheses": ["The activity is escalation.", "The activity is routine."]}
                )
            return "H1: The activity is escalation.\nH2: The activity is routine."
        if "ROLE: ACH matrix scorer" in system:
            if response_schema is not None:
                # E1 (reuters, B) disconfirms routine; E2 (rt, D) disconfirms escalation.
                # ACH must rank escalation first (its disconfirmer is the weaker source).
                return json.dumps(
                    {
                        "rows": [
                            {
                                "hypothesis": "The activity is escalation.",
                                "cells": [
                                    {"evidence": "E1", "assessment": "consistent"},
                                    {"evidence": "E2", "assessment": "inconsistent"},
                                ],
                            },
                            {
                                "hypothesis": "The activity is routine.",
                                "cells": [
                                    {"evidence": "E1", "assessment": "inconsistent"},
                                    {"evidence": "E2", "assessment": "consistent"},
                                ],
                            },
                        ]
                    }
                )
            return "E1 consistent with escalation."
        if "ROLE: Lead Analyst" in system:
            return "I favour H1; the patrols [E1] indicate escalation."
        if "ROLE: Red Team" in system:
            if response_schema is not None:
                return json.dumps(
                    {
                        "critiques": [
                            {
                                "target_hypothesis": "H1",
                                "challenged_claim": "Escalation leans on a single source",
                                "severity": "high",
                                "rationale": "Over-reliant on [E1]",
                                "citations": ["E1"],
                            }
                        ]
                    }
                )
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
                        "key_assumptions": ["the deployment reporting is accurate"],
                        "indicators": ["additional naval movements near the reef"],
                        "alternative_hypothesis": "H2 routine activity is plausible",
                        "collection_requirement": "more independent sources",
                        "intelligence_gaps": ["intentions are unknown"],
                        "critique_response": "Single-source caution noted; held at moderate.",
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
    # ACH ranks escalation first (its only disconfirmer is the low-reliability D source).
    assert state["ach_ranking"][0].hypothesis == "The activity is escalation."
    roles = [role for role, _ in state["transcript"]]
    # The analyst now rebuts the red team's challenge before the adjudicator decides.
    assert roles == ["hypotheses", "ach", "analyst", "red_team", "analyst", "adjudicator"]


def test_debate_rounds_add_exchanges() -> None:
    state = run_deliberation("q?", _EVIDENCE, FakeBackend(), debate_rounds=2)
    assert len(state["critiques"]) == 2
    roles = [role for role, _ in state["transcript"]]
    # Two red-team challenges, each followed by an analyst rebuttal; analyst speaks last.
    assert roles == [
        "hypotheses",
        "ach",
        "analyst",
        "red_team",
        "analyst",
        "red_team",
        "analyst",
        "adjudicator",
    ]


def test_num_hypotheses_is_honored() -> None:
    state = run_deliberation("q?", _EVIDENCE, FakeBackend(), debate_rounds=1, num_hypotheses=1)
    assert len(state["hypotheses"]) == 1  # capped to the requested count


class RecordingBackend:
    """Captures the temperature each role is sampled at, to lock in the per-role policy."""

    name = "rec"

    def __init__(self) -> None:
        self.seen: dict[str, float | None] = {}

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        for marker in (
            "Hypothesis-setter",
            "ACH matrix scorer",
            "Lead Analyst",
            "Red Team",
            "Adjudicator",
        ):
            if f"ROLE: {marker}" in system:
                self.seen[marker] = temperature
        # Seed hypotheses so the ACH node actually runs; everything else falls back.
        if "ROLE: Hypothesis-setter" in system and response_schema is None:
            return "H1: a\nH2: b"
        return ""


def test_roles_sample_at_their_own_temperature() -> None:
    backend = RecordingBackend()
    run_deliberation("q?", _EVIDENCE, backend, debate_rounds=1)
    seen = backend.seen
    # Hot red team for divergent challenges; cold adjudicator for a reproducible finding.
    assert seen["Red Team"] == 0.7
    assert seen["Adjudicator"] == 0.0
    assert seen["ACH matrix scorer"] == 0.1
    assert seen["Red Team"] > seen["Lead Analyst"] > seen["Adjudicator"]


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
    # Structured Analytic Techniques surfaced in the brief.
    assert result.key_assumptions == ["the deployment reporting is accurate"]
    assert result.indicators == ["additional naval movements near the reef"]
    # ACH ranking + the adjudicator's response to the strongest critique are surfaced.
    assert result.ach_ranking and result.ach_ranking[0].hypothesis == "The activity is escalation."
    assert result.critique_response and "moderate" in result.critique_response


class StudentBackend:
    """Stand-in for the MLX-distilled student: one call -> a sectioned brief (the format it
    was trained on). [E9] is out of range and must be dropped on resolution."""

    name = "mlx:student"

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        return (
            "KEY JUDGMENTS:\n- Escalation is likely [E1].\n"
            "CONFIDENCE: moderate — limited corroboration.\n"
            "KEY ASSUMPTIONS: The deployment reporting is accurate.\n"
            "INDICATORS: Additional naval movements near the reef.\n"
            "ALTERNATIVES: routine activity is plausible [E9].\n"
            "INTELLIGENCE GAPS: intentions unknown."
        )


def test_oneshot_brief_parses_and_resolves_citations() -> None:
    from argus.agent.analyst import oneshot_brief

    result = oneshot_brief("q?", _EVIDENCE, StudentBackend())
    assert result.backend == "mlx:student"
    assert result.confidence == "moderate"
    assert result.key_judgments == ["Escalation is likely [E1]."]
    assert result.citations == ["reuters.com:1"]  # [E9] dropped (fabricated)
    assert result.alternatives and "routine" in result.alternatives
    assert result.gaps and "intentions" in result.gaps.lower()
    # Key Assumptions Check + Indicators & Warnings must survive the free-form path too,
    # not just the structured-JSON one (regression: these two SATs were dropped before).
    assert result.key_assumptions == ["The deployment reporting is accurate."]
    assert result.indicators == ["Additional naval movements near the reef."]


def test_generate_brief_student_mode_one_shots(monkeypatch: pytest.MonkeyPatch) -> None:
    from argus.config import Settings

    monkeypatch.setattr(
        "argus.agent.analyst.get_settings",
        lambda: Settings(_env_file=None, brief_mode="student"),
    )
    result = generate_brief("q?", evidence=_EVIDENCE, backend=StudentBackend(), persist=False)
    assert result.backend == "mlx:student"  # one-shot, not the panel
    assert result.confidence == "moderate"
    assert result.citations == ["reuters.com:1"]


def test_citation_resolution_rejects_prose_numbers() -> None:
    from argus.agent.analyst import _resolve_citations

    lm = {"E1": "reuters.com:1", "E2": "apnews.com:2"}
    # explicit labels and a pure number-list both resolve
    assert _resolve_citations("escalation [E1] and [1, 2]", lm) == ["reuters.com:1", "apnews.com:2"]
    # a bare number inside prose is NOT a citation (was the spurious-E2 bug)
    assert _resolve_citations("[2 vessels] massed near the reef", lm) == []
    # an explicit E# still resolves even in a mixed/prose bracket
    assert _resolve_citations("[E1 — see reuters]", lm) == ["reuters.com:1"]
    # a raw doc id resolves
    assert _resolve_citations("[apnews.com:2]", lm) == ["apnews.com:2"]


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
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
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
