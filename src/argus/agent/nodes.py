"""Agent node functions for the deliberation graph.

Each is a pure ``(state, backend) -> partial_state`` function (no LangGraph import, no
hidden globals), so a test can drive a single role with a fake backend. `graph.py`
binds the backend and wires them into the StateGraph.
"""

import re

from argus.agent.llm import LLMBackend
from argus.agent.personas import (
    ADJUDICATOR_SYSTEM,
    ANALYST_SYSTEM,
    HYPOTHESIS_SYSTEM,
    RED_TEAM_SYSTEM,
)
from argus.agent.schemas import Finding, Hypotheses
from argus.agent.state import DeliberationState, format_evidence
from argus.agent.structured import complete_model

_HYPOTHESIS_RE = re.compile(r"^\s*H\d+\s*[:.)\-]\s*(.+?)\s*$")


def _evidence_block(state: DeliberationState) -> str:
    return format_evidence(state.get("evidence", []))


def _hypotheses_block(state: DeliberationState) -> str:
    hyps = state.get("hypotheses", [])
    return "\n".join(f"H{i + 1}: {h}" for i, h in enumerate(hyps)) or "(none yet)"


def _append(state: DeliberationState, role: str, text: str) -> list[tuple[str, str]]:
    return [*state.get("transcript", []), (role, text)]


def propose_hypotheses(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        "List the competing hypotheses."
    )
    structured = complete_model(backend, HYPOTHESIS_SYSTEM, user, Hypotheses)
    if structured is not None and structured.hypotheses:
        hyps = structured.hypotheses
        raw = "\n".join(f"H{i + 1}: {h}" for i, h in enumerate(hyps))
    else:  # JSON failed — parse free-form H1:/H2: lines, else any non-empty lines
        raw = backend.complete(HYPOTHESIS_SYSTEM, user)
        hyps = [m.group(1) for line in raw.splitlines() if (m := _HYPOTHESIS_RE.match(line))]
        if not hyps:
            hyps = [ln.strip("-* ").strip() for ln in raw.splitlines() if ln.strip()][:4]
    return {"hypotheses": hyps, "transcript": _append(state, "hypotheses", raw)}


def analyst(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    critiques = state.get("critiques", [])
    rebuttal = ""
    if critiques:
        rebuttal = (
            "\n\nThe Red Team has challenged your prior assessment:\n"
            + "\n".join(f"- {c}" for c in critiques)
            + "\n\nRevise your assessment, conceding what is fair and defending what holds."
        )
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"HYPOTHESES:\n{_hypotheses_block(state)}{rebuttal}\n\nGive your assessment."
    )
    text = backend.complete(ANALYST_SYSTEM, user)
    return {"analyst": text, "transcript": _append(state, "analyst", text)}


def red_team(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
        f"ANALYST'S ASSESSMENT:\n{state.get('analyst', '')}\n\nChallenge it."
    )
    text = backend.complete(RED_TEAM_SYSTEM, user)
    return {
        "critiques": [*state.get("critiques", []), text],
        "round": state.get("round", 0) + 1,
        "transcript": _append(state, "red_team", text),
    }


def render_finding(finding: Finding) -> str:
    """Render a structured finding into the readable sectioned brief body."""
    judgments = "\n".join(
        f"- {kj.judgment} {' '.join(f'[{c}]' for c in kj.citations)}".rstrip()
        for kj in finding.key_judgments
    )
    alt = finding.alternative_hypothesis
    if finding.collection_requirement:
        alt = f"{alt} Collection requirement: {finding.collection_requirement}".strip()
    gaps = "; ".join(finding.intelligence_gaps) or "(none stated)"
    return (
        f"KEY JUDGMENTS:\n{judgments}\n\n"
        f"CONFIDENCE: {finding.confidence} — {finding.confidence_rationale}\n\n"
        f"ALTERNATIVES: {alt or '(none stated)'}\n\n"
        f"INTELLIGENCE GAPS: {gaps}"
    )


def adjudicate(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    critiques = "\n\n".join(state.get("critiques", [])) or "(none)"
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
        f"ANALYST'S ASSESSMENT:\n{state.get('analyst', '')}\n\n"
        f"RED TEAM'S CHALLENGE(S):\n{critiques}\n\nIssue the finding."
    )
    structured = complete_model(backend, ADJUDICATOR_SYSTEM, user, Finding)
    if structured is not None and structured.key_judgments:
        text = render_finding(structured)
        return {
            "finding": text,
            "finding_struct": structured,
            "transcript": _append(state, "adjudicator", text),
        }
    text = backend.complete(ADJUDICATOR_SYSTEM, user)  # fall back to free-form text
    return {"finding": text, "transcript": _append(state, "adjudicator", text)}
