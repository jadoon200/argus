"""Deterministic domain supervisor for lean all-source fusion.

The expensive analysis remains centralized in ARGUS's existing ACH panel. This supervisor
only decides which source-domain workers should gather evidence for a question, so routing is
instant, explainable, free, and cheap enough for an M3 Pro. OSINT is always the base lane;
Sky (HORUS), Ocean (PHAROS), and Cyber (SENTINEL) wake only when the query touches them.
"""

from typing import Literal

from argus.agent.state import EvidenceItem
from argus.agent.triage import subject_tokens

Lane = Literal["osint", "sky", "ocean", "cyber"]

LANE_ORDER: tuple[Lane, ...] = ("osint", "sky", "ocean", "cyber")
ALL_LANES: frozenset[Lane] = frozenset(LANE_ORDER)

_PROFILES: dict[Lane, frozenset[str]] = {
    "osint": frozenset(),  # the base reporting lane is always consulted
    "sky": frozenset(
        {
            # Lane / project / domain names the user actually types for this lane.
            "air",
            "airborne",
            "aerospace",
            "horus",
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
            # Lane / project names.
            "pharos",
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
            # Lane / project names.
            "sentinel",
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


def route_domains(
    query: str, corpus_hint: list[EvidenceItem] | None = None
) -> tuple[set[Lane], str]:
    """Return the lanes to consult and a human-readable deterministic explanation.

    ``corpus_hint`` is reserved for a future evidence-aware refinement; accepting it now
    keeps the supervisor boundary stable without making routing dependent on embeddings or an
    LLM. Subject-less conversational follow-ups fan out because relevance is unknowable.
    """
    del corpus_hint
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
