"""Reliability-gated confidence cap (agent/calibration.py).

The cap enforces in code the confidence the *sourcing* warrants, so a local model can't
over-read a lone low-reliability source. These tests pin the ceiling per source mix and the
never-raise invariant.
"""

from argus.agent.calibration import apply_confidence_cap, confidence_ceiling
from argus.agent.state import EvidenceItem


def _ev(doc_id: str, source: str, reliability: str) -> EvidenceItem:
    return EvidenceItem(doc_id, "t", source, reliability, 3, "s")


def test_ceiling_low_when_only_low_reliability_sources() -> None:
    ev = [_ev("rt.com:1", "rt.com", "D"), _ev("rt.com:2", "rt.com", "E")]
    ceiling, reason = confidence_ceiling(ev)
    assert ceiling == "low"
    assert reason is not None and "D/E/F" in reason


def test_ceiling_moderate_for_single_credible_source() -> None:
    ev = [_ev("reuters.com:1", "reuters.com", "B")]
    ceiling, reason = confidence_ceiling(ev)
    assert ceiling == "moderate"
    assert reason == "single-source reporting"


def test_ceiling_moderate_without_two_reliable_sources() -> None:
    # One reliable (B) + one merely credible (C): credible sourcing but not two A/B.
    ev = [_ev("reuters.com:1", "reuters.com", "B"), _ev("apnews.com:1", "apnews.com", "C")]
    ceiling, reason = confidence_ceiling(ev)
    assert ceiling == "moderate"
    assert reason is not None and "two independent reliable" in reason


def test_ceiling_high_with_two_independent_reliable_sources() -> None:
    ev = [_ev("reuters.com:1", "reuters.com", "B"), _ev("apnews.com:1", "apnews.com", "A")]
    ceiling, reason = confidence_ceiling(ev)
    assert ceiling == "high"
    assert reason is None


def test_ceiling_grades_by_distinct_source_not_document_count() -> None:
    # Two reliable *documents* from the same outlet is still one source -> not high.
    ev = [_ev("reuters.com:1", "reuters.com", "B"), _ev("reuters.com:2", "reuters.com", "A")]
    ceiling, _ = confidence_ceiling(ev)
    assert ceiling == "moderate"


def test_cap_lowers_high_to_moderate_for_single_source() -> None:
    ev = [_ev("reuters.com:1", "reuters.com", "B")]
    capped, note = apply_confidence_cap("high", ev)
    assert capped == "moderate"
    assert note == "single-source reporting"


def test_cap_never_raises_a_conservative_confidence() -> None:
    # Two reliable sources warrant high, but the model only claimed low -> left untouched.
    ev = [_ev("reuters.com:1", "reuters.com", "B"), _ev("apnews.com:1", "apnews.com", "A")]
    capped, note = apply_confidence_cap("low", ev)
    assert capped == "low"
    assert note is None


def test_cap_passes_through_none_confidence() -> None:
    ev = [_ev("reuters.com:1", "reuters.com", "B")]
    assert apply_confidence_cap(None, ev) == (None, None)


def test_cap_uses_cited_evidence_as_the_basis() -> None:
    # High-tier corroboration exists in the corpus, but the judgment cites only the lone
    # D-rated source -> the cap grades the actual basis, not the ambient evidence.
    ev = [
        _ev("reuters.com:1", "reuters.com", "B"),
        _ev("apnews.com:1", "apnews.com", "A"),
        _ev("rt.com:9", "rt.com", "D"),
    ]
    capped, note = apply_confidence_cap("high", ev, citations=["rt.com:9"])
    assert capped == "low"
    assert note is not None and "D/E/F" in note


def test_cap_falls_back_to_all_evidence_when_citations_do_not_resolve() -> None:
    ev = [_ev("reuters.com:1", "reuters.com", "B"), _ev("apnews.com:1", "apnews.com", "A")]
    # Citations reference nothing in evidence -> grade all gathered evidence (warrants high).
    capped, note = apply_confidence_cap("high", ev, citations=["ghost:1"])
    assert capped == "high"
    assert note is None
