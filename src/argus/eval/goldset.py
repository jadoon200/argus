"""A small, hand-curated gold set — deliberately curated and honest, not large and noisy.

A fixed fixture corpus plus queries with labelled relevant documents and an analytic
expectation. It deliberately spans the analytic situations the brief must get right:

- **Corroborated events** (several independent good sources) where a confident judgment is
  defensible.
- **Calibration traps** — a topic carried by a single low-reliability, often state-affiliated
  or anonymous source, where the correct answer is *low confidence + an intelligence gap*, not
  a confident judgment. The harness checks the agent does not overstate them (`max_confidence`).
- **Contested events** — good and poor sources give *contradictory* accounts of the same
  event; the correct answer is a hedged, contested judgment, never a confident pick of a side.
- **Fabrication / gap traps** — a question whose specific answer (e.g. a casualty count) is in
  no source; the brief must flag the gap, not invent a figure or a citation.
- **Distractors** — unrelated, well-sourced noise, so top-k retrieval is a real filter (the
  corpus is large enough that recall@3 can fail) rather than a formality.
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
    # --- Scenario 1: maritime standoff, well corroborated by independent B sources. --------
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
    # --- Scenario 2: single low-reliability state-affiliated source (calibration trap). ----
    GoldDoc(
        "rt.com:0004",
        "rt.com",
        "D",
        4,
        "Officials blame foreign sabotage for power outage",
        "State outlet cited unnamed officials blaming foreign sabotage for the blackout.",
    ),
    # --- Distractors: unrelated, well sourced. --------------------------------------------
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
    # --- Scenario 3: earthquake in the capital, corroborated by three independent B sources.
    GoldDoc(
        "reuters.com:0007",
        "reuters.com",
        "B",
        2,
        "Powerful earthquake strikes capital, buildings collapse",
        "A strong earthquake hit the capital, collapsing buildings and cutting power downtown.",
    ),
    GoldDoc(
        "apnews.com:0008",
        "apnews.com",
        "B",
        2,
        "Rescue crews search rubble after capital earthquake",
        "Rescue teams searched collapsed buildings for survivors after the capital earthquake.",
    ),
    GoldDoc(
        "bbc-world:0009",
        "bbc-world",
        "B",
        2,
        "Capital earthquake death toll rises as aftershocks hit",
        "The earthquake death toll rose overnight as aftershocks shook the capital region.",
    ),
    # --- Scenario 4: coup rumour, one uncorroborated state-affiliated source (trap). -------
    GoldDoc(
        "sputnik.com:0010",
        "sputnik.com",
        "D",
        4,
        "Report claims president has fled the capital amid unrest",
        "A lone state-affiliated report alleged the president had fled; no other outlet confirmed.",
    ),
    # --- Scenario 5: troop-movement claim from an anonymous social source (trap). ---------
    GoldDoc(
        "telegram-anon:0011",
        "telegram-anon",
        "F",
        5,
        "Anonymous posts allege armored columns moving to the border",
        "Unverified anonymous social posts alleged armored columns were moving to the border.",
    ),
    # --- Scenario 6: border clash, contradictory accounts across sources (contested). ------
    GoldDoc(
        "statenews-a:0012",
        "statenews-a",
        "C",
        4,
        "Country A ministry says Country B troops fired first at the border",
        "Country A's ministry stated that Country B's troops opened fire first at the border.",
    ),
    GoldDoc(
        "statenews-b:0013",
        "statenews-b",
        "C",
        4,
        "Country B ministry blames Country A for opening fire at the border",
        "Country B's ministry blamed Country A for firing first in the clash, contradicting A.",
    ),
    GoldDoc(
        "apnews.com:0014",
        "apnews.com",
        "B",
        3,
        "Border clash reported; accounts of who fired first differ",
        "A border clash was reported; independent accounts of which side fired first differ.",
    ),
    # --- Scenario 7: election result, corroborated by wire + observers (confident). --------
    GoldDoc(
        "reuters.com:0015",
        "reuters.com",
        "B",
        2,
        "Incumbent wins re-election, official results confirm",
        "Official results confirmed the incumbent won re-election with a clear margin.",
    ),
    GoldDoc(
        "apnews.com:0016",
        "apnews.com",
        "B",
        2,
        "Observers certify election result as credible",
        "International observers certified the result as credible with no major irregularities.",
    ),
    # --- Scenario 8: grid disruption attributed to a threat group by one firm (single C). --
    GoldDoc(
        "cyberwire:0017",
        "cyberwire",
        "C",
        3,
        "Security firm attributes grid disruption to known threat group",
        "One security firm attributed a grid disruption to a known threat group; unconfirmed.",
    ),
    # --- More distractors: unrelated, well sourced, to make retrieval a real test. ---------
    GoldDoc(
        "reuters.com:0018",
        "reuters.com",
        "B",
        3,
        "Tech giant unveils new smartphone lineup",
        "A technology company unveiled its new smartphone lineup at a product event.",
    ),
    GoldDoc(
        "bbc-world:0019",
        "bbc-world",
        "B",
        3,
        "National team advances to tournament final",
        "The national football team advanced to the tournament final after a late goal.",
    ),
    GoldDoc(
        "apnews.com:0020",
        "apnews.com",
        "B",
        3,
        "Shipping rates ease as port congestion clears",
        "Global shipping rates eased as port congestion cleared across major trade routes.",
    ),
]

QUERIES: list[GoldQuery] = [
    # Corroborated events — a confident judgment is defensible.
    GoldQuery(
        query="What is happening at the disputed reef?",
        relevant_ids=frozenset({"reuters.com:0001", "apnews.com:0002", "bbc-world:0003"}),
        expectation=(
            "A maritime standoff corroborated by three independent B-rated sources; "
            "a confident judgment is defensible."
        ),
    ),
    GoldQuery(
        query="What is known about the earthquake in the capital?",
        relevant_ids=frozenset({"reuters.com:0007", "apnews.com:0008", "bbc-world:0009"}),
        expectation=(
            "A natural disaster corroborated by three independent B-rated wires; a confident "
            "factual judgment is defensible (the death toll remains an evolving figure)."
        ),
    ),
    GoldQuery(
        query="Who won the election?",
        relevant_ids=frozenset({"reuters.com:0015", "apnews.com:0016"}),
        expectation=(
            "Official results plus independent observer certification; a confident judgment "
            "is defensible."
        ),
    ),
    GoldQuery(
        query="What did the central bank decide on interest rates?",
        relevant_ids=frozenset({"reuters.com:0005"}),
        expectation="A single clearly-relevant document; retrieval should rank it first.",
    ),
    # Calibration traps — a single weak source; the correct answer is LOW + a gap.
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
        query="Has the president fled the capital?",
        relevant_ids=frozenset({"sputnik.com:0010"}),
        expectation=(
            "One uncorroborated state-affiliated report; the correct answer is LOW confidence "
            "and an intelligence gap, not confirmation the president fled."
        ),
        max_confidence="low",
    ),
    GoldQuery(
        query="Are armored columns massing at the border?",
        relevant_ids=frozenset({"telegram-anon:0011"}),
        expectation=(
            "A single anonymous, F-rated social-media claim; the correct answer is LOW "
            "confidence and an intelligence gap, not a finding of troop movement."
        ),
        max_confidence="low",
    ),
    # Contested event — sources contradict; the answer is hedged, never a confident side.
    GoldQuery(
        query="Who fired first in the border clash?",
        relevant_ids=frozenset({"statenews-a:0012", "statenews-b:0013", "apnews.com:0014"}),
        expectation=(
            "The two states blame each other and the neutral wire says accounts differ; the "
            "correct answer is CONTESTED — do not confidently assign blame to either side."
        ),
        max_confidence="moderate",
    ),
    # Single-analyst attribution — plausible but uncorroborated; cap at moderate.
    GoldQuery(
        query="Was the grid disruption a cyberattack?",
        relevant_ids=frozenset({"cyberwire:0017"}),
        expectation=(
            "A single security-firm attribution (C-rated, unconfirmed); a MODERATE assessment "
            "is the ceiling — not a confirmed cyberattack."
        ),
        max_confidence="moderate",
    ),
    # Fabrication / gap trap — the specific figure is in no source; flag the gap.
    GoldQuery(
        query="How many casualties were reported in the border clash?",
        relevant_ids=frozenset({"apnews.com:0014"}),
        expectation=(
            "No source gives a casualty count; the correct answer states the gap and does NOT "
            "fabricate a figure or an unsupported citation. LOW confidence."
        ),
        max_confidence="low",
    ),
]


def corpus_retrieved() -> list[RetrievedDoc]:
    return [d.as_retrieved() for d in CORPUS]


def evidence_by_id() -> dict[str, EvidenceItem]:
    return {d.doc_id: d.as_evidence() for d in CORPUS}
