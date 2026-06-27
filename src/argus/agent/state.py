"""Shared types for the deliberation: evidence, graph state, and the final brief."""

from dataclasses import dataclass, field
from typing import TypedDict

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


@dataclass
class BriefResult:
    query: str
    body: str
    key_judgments: list[str] = field(default_factory=list)
    confidence: str | None = None
    alternatives: str | None = None
    gaps: str | None = None
    citations: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    backend: str = "template"


class DeliberationState(TypedDict, total=False):
    """LangGraph state passed between agent nodes (last-value channels)."""

    query: str
    evidence: list[EvidenceItem]
    hypotheses: list[str]
    analyst: str  # latest analyst assessment
    critiques: list[str]  # accumulated red-team challenges
    transcript: list[tuple[str, str]]  # (role, text) record of the deliberation
    round: int
    finding: str  # adjudicator raw output
    backend: str
