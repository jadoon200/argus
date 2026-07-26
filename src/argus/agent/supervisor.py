"""Deterministic domain/source supervisor for lean all-source fusion.

The expensive analysis remains centralized in ARGUS's existing ACH panel. This supervisor
only decides which source-domain workers should gather evidence for a question, so routing is
instant, explainable, free, and cheap enough for an M3 Pro. Generic domain questions combine
OSINT with the relevant sibling lane; explicitly named sources constrain the gather to exactly
those sources. Subject-less or explicit all-source questions consult every lane.
"""

import re
from typing import Literal

from argus.agent.state import EvidenceItem
from argus.agent.triage import subject_tokens

Lane = Literal["osint", "sky", "ocean", "cyber"]

LANE_ORDER: tuple[Lane, ...] = ("osint", "sky", "ocean", "cyber")
ALL_LANES: frozenset[Lane] = frozenset(LANE_ORDER)

_SOURCE_NAMES: dict[Lane, str] = {
    "osint": "OSINT",
    "sky": "HORUS/Sky",
    "ocean": "PHAROS/Ocean",
    "cyber": "SENTINEL/Cyber",
}
_SOURCE_PATTERNS: dict[Lane, tuple[re.Pattern[str], ...]] = {
    "osint": (
        re.compile(r"\bosint\b", re.IGNORECASE),
        re.compile(r"\bgdelt\b", re.IGNORECASE),
        re.compile(r"\brss\b", re.IGNORECASE),
        re.compile(r"\bopen[- ]source(?: reporting)?\b", re.IGNORECASE),
    ),
    "sky": (re.compile(r"\bhorus\b", re.IGNORECASE),),
    "ocean": (re.compile(r"\bpharos\b", re.IGNORECASE),),
    "cyber": (re.compile(r"\bsentinel\b", re.IGNORECASE),),
}
_ALL_SOURCE = re.compile(
    r"\b(?:all[- ]source|all (?:available )?(?:sources|lanes)|every (?:source|lane))\b",
    re.IGNORECASE,
)

_PROFILES: dict[Lane, frozenset[str]] = {
    "osint": frozenset(),  # generic queries use the base reporting lane
    "sky": frozenset(
        {
            # Domain names and air-domain vocabulary. The project name is handled separately
            # because explicitly naming HORUS constrains the source instead of broadening it.
            "air",
            "airborne",
            "aerospace",
            "sky",
            # Air-domain vocabulary.
            "adsb",
            "aerial",
            "aircraft",
            "airfield",
            "airline",
            "airport",
            "airspace",
            "aviation",
            "drone",
            "flight",
            "gnss",
            "gps",
            "jamming",
            "jet",
            "plane",
            "radar",
            "runway",
            "squawk",
            "transponder",
        }
    ),
    "ocean": frozenset(
        {
            # Maritime-domain vocabulary.
            "ais",
            "boat",
            "coastguard",
            "fleet",
            "maritime",
            "naval",
            "navy",
            "ocean",
            "port",
            "reef",
            "sea",
            "seaborne",
            "ship",
            "shipping",
            "strait",
            "tanker",
            "vessel",
            "warship",
        }
    ),
    "cyber": frozenset(
        {
            # Cyber-domain vocabulary.
            "apt",
            "breach",
            "cve",
            "cyber",
            "cyberattack",
            "ddos",
            "exploit",
            "exploitation",
            "hack",
            "hacker",
            "intrusion",
            "malware",
            "network",
            "phishing",
            "ransomware",
            "rootkit",
            "trojan",
            "vulnerability",
            "zero-day",
            "zeroday",
        }
    ),
}


def _explicit_sources(query: str) -> set[Lane]:
    return {
        lane
        for lane, patterns in _SOURCE_PATTERNS.items()
        if any(pattern.search(query) for pattern in patterns)
    }


def route_domains(
    query: str, corpus_hint: list[EvidenceItem] | None = None
) -> tuple[set[Lane], str]:
    """Return the lanes to consult and a human-readable deterministic explanation.

    ``corpus_hint`` is reserved for a future evidence-aware refinement; accepting it now
    keeps the supervisor boundary stable without making routing dependent on embeddings or an
    LLM. Explicitly named source systems take precedence over generic domain vocabulary:
    ``overview of the ocean`` routes to OSINT + Ocean, while ``from PHAROS`` routes only to
    Ocean. Naming multiple systems selects exactly those systems. Subject-less conversational
    follow-ups and explicit all-source requests fan out because no narrower source scope exists.
    """
    del corpus_hint
    if _ALL_SOURCE.search(query):
        return set(ALL_LANES), "explicit all-source request — consulted every lane"

    explicit = _explicit_sources(query)
    if explicit:
        selected = ", ".join(_SOURCE_NAMES[lane] for lane in LANE_ORDER if lane in explicit)
        return explicit, f"explicit source scope — consulted only: {selected}"

    tokens = subject_tokens(query)
    if not tokens:
        return set(
            ALL_LANES
        ), "subject-less query — consulted every lane because relevance is unknowable"

    lanes: set[Lane] = {"osint"}
    matches: list[str] = []
    routing_tokens = tokens | {token[:-1] for token in tokens if token.endswith("s")}
    for lane in ("sky", "ocean", "cyber"):
        hit = sorted(routing_tokens & _PROFILES[lane])
        if hit:
            lanes.add(lane)
            matches.append(f"{lane} matched {', '.join(hit)}")

    if not matches:
        return lanes, "OSINT base lane only — no Sky, Ocean, or Cyber domain signal in the query"
    return lanes, "OSINT base lane; " + "; ".join(matches)
