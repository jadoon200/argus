"""Shared types for the deliberation: evidence, graph state, and the final brief."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from argus.agent.schemas import AchMatrix, Critique, Finding
from argus.nlp.reliability import admiralty_code, credibility_label, reliability_label

EVIDENCE_EPISODE_WINDOW = timedelta(minutes=30)
_TITLE_TOKEN = re.compile(r"[^a-z0-9]+")


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
    # Cached dense embedding (carried from the Document row when retrieved) so downstream
    # signals — e.g. framing-divergence effort routing — need no re-embedding. Not rendered.
    embedding: list[float] | None = None

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


def parse_evidence_time(value: str | None) -> datetime | None:
    """Parse an ISO evidence timestamp to comparable UTC, tolerating date-only values."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _content_identity(item: EvidenceItem) -> tuple[str, str] | None:
    title = _TITLE_TOKEN.sub(" ", item.title.casefold()).strip()
    source = item.source.casefold().strip()
    return (source, title) if source and title else None


def _detail_score(item: EvidenceItem) -> tuple[int, int, int]:
    """Prefer the representative with the richest analyst-visible context."""
    return (len(item.summary or ""), int(item.url is not None), int(item.published is not None))


def deduplicate_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Collapse exact IDs and same-source near-duplicate evidence episodes.

    Multiple sources reporting one event remain separate because corroboration is diagnostic.
    Within one source, the same normalized title inside a 30-minute window is one evidence
    episode; the richest representative replaces the first while preserving its rank slot.
    Items without a usable timestamp are only de-duplicated by exact ``doc_id``.
    """
    kept: list[EvidenceItem] = []
    id_indexes: dict[str, int] = {}
    clusters: dict[tuple[str, str], list[tuple[list[datetime], int]]] = {}
    for item in items:
        duplicate_index = id_indexes.get(item.doc_id)
        if duplicate_index is not None:
            if _detail_score(item) > _detail_score(kept[duplicate_index]):
                kept[duplicate_index] = item
            continue
        identity = _content_identity(item)
        timestamp = parse_evidence_time(item.published)
        if identity is None or timestamp is None:
            id_indexes[item.doc_id] = len(kept)
            kept.append(item)
            continue

        matched: tuple[list[datetime], int] | None = None
        for cluster in clusters.get(identity, []):
            if any(abs(timestamp - existing) <= EVIDENCE_EPISODE_WINDOW for existing in cluster[0]):
                matched = cluster
                break
        if matched is None:
            index = len(kept)
            id_indexes[item.doc_id] = index
            kept.append(item)
            clusters.setdefault(identity, []).append(([timestamp], index))
            continue

        times, index = matched
        id_indexes[item.doc_id] = index
        times.append(timestamp)
        if _detail_score(item) > _detail_score(kept[index]):
            kept[index] = item
    return kept


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
    # Set when the reliability-gated cap lowered the model's stated confidence (calibration.py).
    confidence_note: str | None = None
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
    # Transparency for the adaptive path (response metadata, not persisted): which mode the
    # effort router chose and why, and how many documents collect-on-demand fetched.
    mode: str | None = None
    mode_reason: str | None = None
    auto_collected: int | None = None
    # Domain-routing transparency (fresh retrieval only): workers actually consulted and
    # the deterministic supervisor's explanation. Metadata only; never persisted.
    lanes_consulted: list[str] = field(default_factory=list)
    lane_reason: str | None = None


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
