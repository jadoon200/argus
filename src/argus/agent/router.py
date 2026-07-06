"""Adaptive effort routing — decide, per question, whether the full panel is worth minutes.

A chat can't ask the user to know when Analysis of Competing Hypotheses matters; the system
should route its own analytic effort the way an analyst triages their day. The router is
**deterministic and instant** (no LLM) and its decision is **explained** to the user, never
silent. It escalates to the deliberation panel exactly where the panel earns its cost:

- **Attribution / causality questions** ("who is behind…", "was X caused by…") — competing
  explanations are the whole question, which is what ACH exists for.
- **Low-reliability-only sourcing** — every relevant item is D/E/F; the calibration
  discipline (red-team + adjudicator) is what stops an overstated claim.
- **Contested framing** — the retrieved evidence *disagrees* (framing divergence over the
  stored embeddings, the same signal as `nlp/contest.py`); disagreement is where a single
  pass is most likely to pick a side silently.

Everything else — descriptive/summary questions over corroborated reporting — gets the
quick single-pass brief. The escalation signals are measured on the evidence, not guessed
from the words alone.
"""

import re

import numpy as np

from argus.agent.state import EvidenceItem
from argus.nlp.contest import framing_divergence

# Question shapes where competing explanations ARE the question (ACH territory).
_ATTRIBUTION_RE = re.compile(
    r"\bwho\s+(?:is|was|are|were)?\s*(?:really\s+)?(?:behind|responsible)\b"
    r"|\bwho\s+(?:did|caused|ordered|fired|attacked|launched|sabotaged)\b"
    r"|\b(?:was|were|is|are)\s+.{0,60}\b(?:caused|carried out|orchestrated|staged|ordered)\b"
    r"|\bwhy\s+(?:did|is|was|are|were)\b"
    r"|\battributi(?:on|ng)\b|\bculpab|\bwho fired first\b|\bblame\b",
    re.IGNORECASE,
)

_LOW_TIERS = frozenset("DEF")


def _divergence(evidence: list[EvidenceItem]) -> float | None:
    """Framing divergence across the evidence's cached embeddings (None if too few)."""
    vecs = [e.embedding for e in evidence if e.embedding]
    if len(vecs) < 2:
        return None
    return framing_divergence(np.asarray(vecs, dtype=np.float32))


def decide_mode(
    query: str,
    evidence: list[EvidenceItem],
    divergence_threshold: float = 0.30,
    scatter_cap: float = 0.75,
) -> tuple[str, str]:
    """Route a question to ("quick" | "panel", human-readable reason). Deterministic.

    Contested framing is a *band*, not a tail: same-story-different-framing evidence lands
    at moderate divergence, while near-orthogonal embeddings (>= `scatter_cap`) mean the
    retrieved docs are about *different things* — broad/scattered corpus coverage, which a
    single pass summarizes fine. (Caught live: a descriptive question over a topically
    scattered corpus mis-routed to the panel at divergence 1.00.)"""
    if _ATTRIBUTION_RE.search(query or ""):
        return "panel", "attribution/causality question — competing explanations need ACH"

    graded = [e for e in evidence if e.reliability]
    if graded and all(e.reliability.upper()[0] in _LOW_TIERS for e in graded):
        return "panel", "only low-reliability sourcing — calibration discipline required"

    div = _divergence(evidence)
    if div is not None and divergence_threshold <= div < scatter_cap:
        return "panel", f"sources disagree in framing (divergence {div:.2f}) — contested"
    if div is not None and div >= scatter_cap:
        return "quick", "topically scattered coverage — single pass summarizes what exists"

    return "quick", "descriptive question over corroborated reporting — single pass suffices"
