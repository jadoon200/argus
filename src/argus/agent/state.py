"""Shared types for the deliberation: evidence, graph state, and the final brief."""

from dataclasses import dataclass, field
from typing import TypedDict

from argus.agent.schemas import AchMatrix, Critique, Finding
from argus.nlp.reliability import admiralty_code, credibility_label, reliability_label


@dataclass(frozen=True)
class EvidenceItem:
    doc_id: str
    title: str
    source: str
    reliability: str  # Admiralty A-F
    credibility: int | None  # Admiralty 1-6
    summary: str | None = None
    published: str | None = None  # ISO date string (display only)
    url: str | None = None

    def rating(self) -> str:
        return admiralty_code(self.reliability, self.credibility)

    def as_line(self, label: str) -> str:
        when = f" ({self.published})" if self.published else ""
        body = self.summary or self.title
        return (
            f"[{label}] {self.rating()} "
            f"({reliability_label(self.reliability)}; {credibility_label(self.credibility)}) "
            f"{self.source}{when}: {self.title}. {body}"
        )


def evidence_labels(items: list[EvidenceItem]) -> dict[str, str]:
    """Map the citation label shown to the agents (E1, E2, …) back to the doc id."""
    return {f"E{i + 1}": item.doc_id for i, item in enumerate(items)}


def format_evidence(items: list[EvidenceItem]) -> str:
    """Render evidence with short [E#] citation handles (LLMs copy these reliably;
    long hash doc ids they do not)."""
    if not items:
        return "(no open-source evidence retrieved)"
    return "\n".join(item.as_line(f"E{i + 1}") for i, item in enumerate(items))


@dataclass(frozen=True)
class HypothesisScore:
    """One hypothesis's ACH score — defined here (a shared deliberation type) rather than
    in ach.py so this module has no import cycle and LangGraph can resolve the state hints."""

    hypothesis: str
    inconsistency: float  # reliability-weighted disconfirming evidence (lower = stronger)
    consistent: int  # count of consistent cells (weak tiebreak; non-diagnostic alone)
    inconsistent: int  # count of inconsistent cells


@dataclass
class BriefResult:
    query: str
    body: str
    key_judgments: list[str] = field(default_factory=list)
    confidence: str | None = None
    # Cross-sample agreement behind the confidence, when self-consistency (assurance) ran.
    confidence_agreement: float | None = None
    key_assumptions: list[str] = field(default_factory=list)
    indicators: list[str] = field(default_factory=list)
    alternatives: str | None = None
    gaps: str | None = None
    citations: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    ach_ranking: list["HypothesisScore"] = field(default_factory=list)  # ACH, strongest first
    critique_response: str | None = None  # how the finding answers the strongest challenge
    # The evidence the brief was generated from (incl. cyber-fusion items), so callers
    # can show the cited items with their Admiralty ratings without a second retrieval.
    evidence: list[EvidenceItem] = field(default_factory=list)
    backend: str = "template"


class DeliberationState(TypedDict, total=False):
    """LangGraph state passed between agent nodes (last-value channels)."""

    query: str
    evidence: list[EvidenceItem]
    num_hypotheses: int  # how many competing hypotheses to enumerate (ACH)
    hypotheses: list[str]
    ach_matrix: AchMatrix | None  # evidence x hypothesis consistency matrix
    ach_ranking: list["HypothesisScore"]  # hypotheses ranked by least disconfirming evidence
    analyst: str  # latest analyst assessment
    critiques: list[str]  # accumulated red-team challenges (rendered text, for prompts)
    critiques_struct: list[Critique]  # accumulated structured red-team critiques
    transcript: list[tuple[str, str]]  # (role, text) record of the deliberation
    round: int
    finding: str  # adjudicator output rendered to text (for the brief body)
    finding_struct: Finding | None  # validated structured finding, when JSON succeeded
    backend: str
