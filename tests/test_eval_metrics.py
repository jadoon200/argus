from argus.eval.metrics import (
    citation_coverage,
    citation_markers,
    exceeds_confidence,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k() -> None:
    assert recall_at_k(["a", "b", "c", "d"], frozenset({"a", "c"}), 3) == 1.0
    assert recall_at_k(["x", "y", "a"], frozenset({"a", "b"}), 2) == 0.0
    assert recall_at_k(["a"], frozenset(), 3) == 1.0  # no relevant docs -> trivially 1.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "a", "b"], frozenset({"a"})) == 0.5
    assert reciprocal_rank(["a"], frozenset({"a"})) == 1.0
    assert reciprocal_rank(["x", "y"], frozenset({"a"})) == 0.0


def test_citation_markers() -> None:
    assert citation_markers("foo [E1] bar [E2, E3]") == ["E1", "E2", "E3"]
    assert citation_markers("no markers here") == []


def test_citation_coverage() -> None:
    assert citation_coverage(["a [E1]", "b", "c [E2]"]) == 2 / 3
    assert citation_coverage([]) == 0.0


def test_exceeds_confidence() -> None:
    assert exceeds_confidence("high", "low") is True
    assert exceeds_confidence("moderate", "low") is True
    assert exceeds_confidence("low", "low") is False
    assert exceeds_confidence("moderate", None) is False  # no cap
    assert exceeds_confidence(None, "low") is False
