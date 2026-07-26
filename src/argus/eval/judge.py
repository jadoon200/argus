"""LLM-as-judge scoring for the two reading-dependent metrics.

Deterministic checks (recall, citation coverage, fabrication, calibration) can't tell
whether a cited source actually *supports* a claim, or whether a judgment is *grounded*
in the evidence at all — that needs reading. A judge model (the same free local backend)
reads each key judgment against the evidence and returns a structured verdict.

Optional and off the CI path: the deterministic eval runs with no LLM; this adds the two
numbers only when a backend is available. Self-judging (the same family scoring itself)
is a known weakness — spot-check against human labels; recorded honestly in docs/EVAL.md.
"""

from pydantic import BaseModel

from argus.agent.llm import LLMBackend
from argus.agent.state import EvidenceItem, deduplicate_evidence, format_evidence
from argus.agent.structured import complete_model

_JUDGE_SYSTEM = """You are a strict intelligence-review editor. You are given open-source
EVIDENCE (each item labelled [E#] with a NATO Admiralty rating) and a single analytic
JUDGMENT. Judge ONLY against the evidence shown — never outside knowledge — and be strict:
an overstated, uncited, or unsupported claim fails.

Return a JSON verdict:
- grounded: true if SOME evidence item supports the judgment's substance, else false.
- supported: true if the SPECIFIC [E#] item(s) the judgment cites actually support it;
  false if it cites nothing or the cited item doesn't back the claim."""


class Verdict(BaseModel):
    grounded: bool = False
    supported: bool = False
    reason: str = ""


class JudgeScores(BaseModel):
    n: int = 0  # judgments actually scored (unparseable verdicts are skipped, not penalised)
    grounded: int = 0
    supported: int = 0

    @property
    def faithfulness(self) -> float:
        return self.grounded / self.n if self.n else 1.0

    @property
    def citation_support(self) -> float:
        return self.supported / self.n if self.n else 1.0


def judge_brief(
    judgments: list[str], evidence: list[EvidenceItem], backend: LLMBackend
) -> JudgeScores:
    """Score each key judgment for groundedness and citation support (one judge call each)."""
    evidence = deduplicate_evidence(evidence)
    block = format_evidence(evidence)
    scores = JudgeScores()
    for judgment in judgments:
        if not judgment.strip():
            continue
        user = f"EVIDENCE:\n{block}\n\nJUDGMENT: {judgment}\n\nReturn your verdict."
        verdict = complete_model(backend, _JUDGE_SYSTEM, user, Verdict, temperature=0.0)
        if verdict is None:  # judge produced no usable JSON — skip, don't penalise
            continue
        scores.n += 1
        scores.grounded += int(verdict.grounded)
        scores.supported += int(verdict.supported)
    return scores
