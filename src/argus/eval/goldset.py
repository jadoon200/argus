"""A small, hand-curated gold set — deliberately small and honest, not large and noisy.

A fixed fixture corpus plus queries with labelled relevant documents and an analytic
expectation, including a calibration TRAP: a topic carried by a single low-reliability,
state-affiliated source where the correct answer is *low confidence + an intelligence
gap*, not a confident judgment. The harness checks the agent does not overstate it.
"""

from dataclasses import dataclass

from argus.agent.state import EvidenceItem
from argus.nlp.retrieval import RetrievedDoc


@dataclass(frozen=True)
class GoldDoc:
    doc_id: str
    source: str
    reliability: str
    credibility: int
    title: str
    summary: str

    def as_retrieved(self) -> RetrievedDoc:
        return RetrievedDoc(self.doc_id, f"{self.title}. {self.summary}", embedding=None)

    def as_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            doc_id=self.doc_id,
            title=self.title,
            source=self.source,
            reliability=self.reliability,
            credibility=self.credibility,
            summary=self.summary,
        )


@dataclass(frozen=True)
class GoldQuery:
    query: str
    relevant_ids: frozenset[str]
    expectation: str
    # Calibration trap: the brief should NOT exceed this confidence (None = no cap).
    max_confidence: str | None = None


CORPUS: list[GoldDoc] = [
    # Scenario 1 — maritime standoff, well corroborated by independent B sources.
    GoldDoc(
        "reuters.com:0001",
        "reuters.com",
        "B",
        2,
        "Coast guard vessels in standoff near disputed reef",
        "Two coast guard ships confronted fishing boats at the contested reef on Tuesday.",
    ),
    GoldDoc(
        "apnews.com:0002",
        "apnews.com",
        "B",
        2,
        "Navy shadows coast guard near contested reef",
        "Naval vessels were observed near the disputed reef during the maritime standoff.",
    ),
    GoldDoc(
        "bbc-world:0003",
        "bbc-world",
        "B",
        2,
        "Tensions rise over disputed reef as ships mass",
        "Multiple vessels massed near the reef amid rising tension between the two coast guards.",
    ),
    # Scenario 2 — single low-reliability, state-affiliated source (the calibration trap).
    GoldDoc(
        "rt.com:0004",
        "rt.com",
        "D",
        4,
        "Officials blame foreign sabotage for power outage",
        "State outlet cited unnamed officials blaming foreign sabotage for the blackout.",
    ),
    # Distractors — unrelated, well-sourced.
    GoldDoc(
        "reuters.com:0005",
        "reuters.com",
        "B",
        3,
        "Central bank holds interest rates steady",
        "The central bank kept its benchmark interest rate unchanged, citing easing inflation.",
    ),
    GoldDoc(
        "bbc-world:0006",
        "bbc-world",
        "B",
        3,
        "Heatwave breaks temperature records across Europe",
        "A severe heatwave set new temperature records across the European continent this week.",
    ),
]

QUERIES: list[GoldQuery] = [
    GoldQuery(
        query="What is happening at the disputed reef?",
        relevant_ids=frozenset({"reuters.com:0001", "apnews.com:0002", "bbc-world:0003"}),
        expectation=(
            "A maritime standoff corroborated by three independent B-rated sources; "
            "a confident judgment is defensible."
        ),
    ),
    GoldQuery(
        query="Was the nationwide power outage caused by foreign sabotage?",
        relevant_ids=frozenset({"rt.com:0004"}),
        expectation=(
            "Single uncorroborated D-rated state-affiliated source; the correct answer is "
            "LOW confidence plus an intelligence gap, not a finding of sabotage."
        ),
        max_confidence="low",
    ),
    GoldQuery(
        query="What did the central bank decide on interest rates?",
        relevant_ids=frozenset({"reuters.com:0005"}),
        expectation="A single clearly-relevant document; retrieval should rank it first.",
    ),
]


def corpus_retrieved() -> list[RetrievedDoc]:
    return [d.as_retrieved() for d in CORPUS]


def evidence_by_id() -> dict[str, EvidenceItem]:
    return {d.doc_id: d.as_evidence() for d in CORPUS}
