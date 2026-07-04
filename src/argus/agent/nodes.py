"""Agent node functions for the deliberation graph.

Each is a pure ``(state, backend) -> partial_state`` function (no LangGraph import, no
hidden globals), so a test can drive a single role with a fake backend. `graph.py`
binds the backend and wires them into the StateGraph.

Each role samples at its own temperature: the red team runs hot (divergent challenges),
the adjudicator cold (a deterministic, reproducible finding), with the analyst and the
ACH scorer in between.
"""

import re

from argus.agent import ach
from argus.agent.llm import LLMBackend
from argus.agent.personas import (
    ACH_SYSTEM,
    ADJUDICATOR_SYSTEM,
    ANALYST_SYSTEM,
    HYPOTHESIS_SYSTEM,
    RED_TEAM_SYSTEM,
)
from argus.agent.schemas import AchMatrix, Critique, Critiques, Finding, Hypotheses
from argus.agent.state import DeliberationState, format_evidence
from argus.agent.structured import complete_model, safe_complete

_HYPOTHESIS_RE = re.compile(r"^\s*H\d+\s*[:.)\-]\s*(.+?)\s*$")
_DEFAULT_HYPOTHESES = 3

# Per-role sampling temperatures (innovation D): a hot red team explores more divergent
# challenges; a cold adjudicator yields a reproducible, well-calibrated finding.
HYPOTHESIS_TEMP = 0.5
ACH_TEMP = 0.1
ANALYST_TEMP = 0.2
RED_TEAM_TEMP = 0.7
ADJUDICATOR_TEMP = 0.0


def _evidence_block(state: DeliberationState) -> str:
    return format_evidence(state.get("evidence", []))


def _hypotheses_block(state: DeliberationState) -> str:
    hyps = state.get("hypotheses", [])
    return "\n".join(f"H{i + 1}: {h}" for i, h in enumerate(hyps)) or "(none yet)"


def _ranking_block(state: DeliberationState) -> str:
    return ach.render_ranking(state.get("ach_ranking", []))


def _append(state: DeliberationState, role: str, text: str) -> list[tuple[str, str]]:
    return [*state.get("transcript", []), (role, text)]


def propose_hypotheses(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    n = state.get("num_hypotheses", _DEFAULT_HYPOTHESES)
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"List exactly {n} competing hypotheses."
    )
    structured = complete_model(
        backend, HYPOTHESIS_SYSTEM, user, Hypotheses, temperature=HYPOTHESIS_TEMP
    )
    if structured is not None and structured.hypotheses:
        hyps = structured.hypotheses[:n]
        raw = "\n".join(f"H{i + 1}: {h}" for i, h in enumerate(hyps))
    else:  # JSON failed — parse free-form H1:/H2: lines, else any non-empty lines
        raw = safe_complete(backend, HYPOTHESIS_SYSTEM, user, temperature=HYPOTHESIS_TEMP)
        hyps = [m.group(1) for line in raw.splitlines() if (m := _HYPOTHESIS_RE.match(line))]
        if not hyps:
            hyps = [ln.strip("-* ").strip() for ln in raw.splitlines() if ln.strip()]
        hyps = hyps[:n]
    return {"hypotheses": hyps, "transcript": _append(state, "hypotheses", raw)}


def score_hypotheses(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    """ACH: rate each hypothesis against each evidence item, then rank by least
    disconfirming evidence. Falls back to a neutral (no-signal) matrix if the model
    doesn't return a usable one, so the ranking is always present and honest."""
    hyps = state.get("hypotheses", [])
    evidence = state.get("evidence", [])
    matrix: AchMatrix | None = None
    if hyps:
        user = (
            f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
            f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
            "Score every hypothesis against every evidence item."
        )
        structured = complete_model(backend, ACH_SYSTEM, user, AchMatrix, temperature=ACH_TEMP)
        if structured is not None and structured.rows:
            matrix = structured
    if matrix is None:
        matrix = ach.neutral_matrix(hyps)
    ranking = ach.score_matrix(matrix, evidence)
    return {
        "ach_matrix": matrix,
        "ach_ranking": ranking,
        "transcript": _append(state, "ach", ach.render_ranking(ranking)),
    }


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
        f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
        f"ACH RANKING (least-disconfirmed first):\n{_ranking_block(state)}{rebuttal}\n\n"
        "Give your assessment."
    )
    text = safe_complete(backend, ANALYST_SYSTEM, user, temperature=ANALYST_TEMP)
    return {"analyst": text, "transcript": _append(state, "analyst", text)}


def _render_critiques(critiques: list[Critique]) -> str:
    lines = []
    for c in critiques:
        cites = " ".join(f"[{x}]" for x in c.citations)
        target = f" (vs {c.target_hypothesis})" if c.target_hypothesis else ""
        lines.append(f"[{c.severity}]{target} {c.challenged_claim or c.rationale} {cites}".rstrip())
    return "\n".join(lines)


def red_team(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    user = (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
        f"ANALYST'S ASSESSMENT:\n{state.get('analyst', '')}\n\nChallenge it."
    )
    structured = complete_model(
        backend, RED_TEAM_SYSTEM, user, Critiques, temperature=RED_TEAM_TEMP
    )
    if structured is not None and structured.critiques:
        new_struct = structured.critiques
        text = _render_critiques(new_struct)
    else:  # free-form fallback: keep the prose, no structured critiques this round
        new_struct = []
        text = safe_complete(backend, RED_TEAM_SYSTEM, user, temperature=RED_TEAM_TEMP)
    return {
        "critiques": [*state.get("critiques", []), text],
        "critiques_struct": [*state.get("critiques_struct", []), *new_struct],
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
    assumptions = "; ".join(finding.key_assumptions) or "(none stated)"
    indicators = "; ".join(finding.indicators) or "(none stated)"
    gaps = "; ".join(finding.intelligence_gaps) or "(none stated)"
    body = (
        f"KEY JUDGMENTS:\n{judgments}\n\n"
        f"CONFIDENCE: {finding.confidence} — {finding.confidence_rationale}\n\n"
        f"KEY ASSUMPTIONS: {assumptions}\n\n"
        f"INDICATORS: {indicators}\n\n"
        f"ALTERNATIVES: {alt or '(none stated)'}\n\n"
        f"INTELLIGENCE GAPS: {gaps}"
    )
    if finding.critique_response:
        body += f"\n\nRED TEAM RESPONSE: {finding.critique_response}"
    return body


def adjudicator_prompt(state: DeliberationState) -> str:
    """The adjudicator's user message — reused by the assurance resampler (self-consistency)."""
    struct_critiques = state.get("critiques_struct", [])
    critiques = (
        _render_critiques(struct_critiques)
        if struct_critiques
        else "\n\n".join(state.get("critiques", [])) or "(none)"
    )
    return (
        f"QUESTION: {state['query']}\n\nEVIDENCE:\n{_evidence_block(state)}\n\n"
        f"HYPOTHESES:\n{_hypotheses_block(state)}\n\n"
        f"ACH RANKING (least-disconfirmed first):\n{_ranking_block(state)}\n\n"
        f"ANALYST'S ASSESSMENT:\n{state.get('analyst', '')}\n\n"
        f"RED TEAM'S CHALLENGE(S):\n{critiques}\n\nIssue the finding."
    )


def adjudicate(state: DeliberationState, backend: LLMBackend) -> DeliberationState:
    user = adjudicator_prompt(state)
    structured = complete_model(
        backend, ADJUDICATOR_SYSTEM, user, Finding, temperature=ADJUDICATOR_TEMP
    )
    if structured is not None and structured.key_judgments:
        text = render_finding(structured)
        return {
            "finding": text,
            "finding_struct": structured,
            "transcript": _append(state, "adjudicator", text),
        }
    text = safe_complete(
        backend, ADJUDICATOR_SYSTEM, user, temperature=ADJUDICATOR_TEMP
    )  # free-form
    return {"finding": text, "transcript": _append(state, "adjudicator", text)}
