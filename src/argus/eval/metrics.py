"""Pure scoring functions for the eval harness (deterministic, no LLM required)."""

import re

_MARKER_RE = re.compile(r"\[([^\]]+)\]")
_CONFIDENCE_ORDER = {"low": 0, "moderate": 1, "high": 2}


def recall_at_k(retrieved_ids: list[str], relevant_ids: frozenset[str], k: int) -> float:
    """Fraction of relevant documents present in the top-k retrieved."""
    if not relevant_ids:
        return 1.0
    topk = set(retrieved_ids[:k])
    return len(topk & relevant_ids) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: frozenset[str]) -> float:
    """1/rank of the first relevant document (0 if none retrieved)."""
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def citation_markers(text: str) -> list[str]:
    """Every citation token the model wrote, e.g. ['E1', 'E3'] (pre-resolution)."""
    tokens: list[str] = []
    for inner in _MARKER_RE.findall(text):
        tokens.extend(t for t in re.split(r"[,\s]+", inner.strip()) if t)
    return tokens


def citation_coverage(key_judgments: list[str]) -> float:
    """Fraction of key-judgment lines that carry at least one citation marker."""
    if not key_judgments:
        return 0.0
    cited = sum(1 for kj in key_judgments if _MARKER_RE.search(kj))
    return cited / len(key_judgments)


def exceeds_confidence(confidence: str | None, cap: str | None) -> bool:
    """True if `confidence` is stronger than `cap` (used for the calibration trap)."""
    if cap is None or confidence is None:
        return False
    return _CONFIDENCE_ORDER.get(confidence, 0) > _CONFIDENCE_ORDER.get(cap, 2)
