"""Contested-event detection — the inverse of narrative coordination.

Narrative watch flags sources *agreeing* (a synchronized push). This flags sources
*disagreeing*: within one event (documents about the same happening), how far apart are
their framings? High framing divergence — especially across reliability tiers, e.g. a
state-affiliated outlet telling a different story than the wire services about the same
event — is a prized analytic signal: contradictions reveal deception, error, or a
developing situation. Deterministic (embedding geometry), so it needs no LLM and is
testable and CI-safe.
"""

import numpy as np

from argus.nlp.embed import Vector
from argus.nlp.events import _normalize

_HIGH_RELIABILITY = {"A", "B", "C"}
_LOW_RELIABILITY = {"D", "E", "F"}


def framing_divergence(embeddings: Vector) -> float:
    """1 - the minimum pairwise cosine among member framings, clamped to [0,1].

    0 means every source frames the event identically; higher means the two most
    divergent framings differ — the event is contested.
    """
    n = len(embeddings)
    if n < 2:
        return 0.0
    normed = [_normalize(embeddings[i]) for i in range(n)]
    min_cos = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            min_cos = min(min_cos, float(np.dot(normed[i], normed[j])))
    return max(0.0, min(1.0, 1.0 - min_cos))


def crosses_reliability_tiers(reliabilities: list[str]) -> bool:
    """True if both a high- (A-C) and a low-reliability (D-F) source frame the event --
    the case where a divergence most warrants an analyst's attention."""
    grades = {(r or "F").upper()[:1] for r in reliabilities}
    return bool(grades & _HIGH_RELIABILITY) and bool(grades & _LOW_RELIABILITY)
