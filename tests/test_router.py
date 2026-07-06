from argus.agent.router import decide_mode
from argus.agent.state import EvidenceItem


def _ev(reliability: str, embedding: list[float] | None = None, i: int = 0) -> EvidenceItem:
    return EvidenceItem(
        doc_id=f"s{i}:{i}",
        title="Report",
        source=f"s{i}",
        reliability=reliability,
        credibility=3,
        summary="reporting text",
        embedding=embedding,
    )


def test_attribution_questions_escalate_to_panel() -> None:
    ev = [_ev("B", i=1), _ev("B", i=2)]
    for q in (
        "Who is behind the pipeline sabotage?",
        "Was the blackout caused by a cyberattack?",
        "Who fired first in the border clash?",
        "Why did the government collapse?",
    ):
        mode, reason = decide_mode(q, ev)
        assert mode == "panel", q
        assert "attribution" in reason or "causality" in reason


def test_low_reliability_only_sourcing_escalates() -> None:
    mode, reason = decide_mode("What is happening at the border?", [_ev("D", i=1), _ev("F", i=2)])
    assert mode == "panel"
    assert "low-reliability" in reason


def test_contested_framing_escalates() -> None:
    # Moderate divergence (cosine 0.5 -> div 0.5): same story, different framing -> panel.
    ev = [_ev("B", [1.0, 0.0], i=1), _ev("B", [0.5, 0.866], i=2)]
    mode, reason = decide_mode("What happened at the summit?", ev)
    assert mode == "panel"
    assert "disagree" in reason


def test_topically_scattered_coverage_stays_quick() -> None:
    # Orthogonal embeddings (div 1.0) = docs about DIFFERENT things, not disagreement —
    # broad corpus coverage must not escalate. (Live-caught mis-route.)
    ev = [_ev("B", [1.0, 0.0], i=1), _ev("B", [0.0, 1.0], i=2)]
    mode, reason = decide_mode("Assess tensions in the region", ev)
    assert mode == "quick"
    assert "scattered" in reason


def test_descriptive_corroborated_questions_stay_quick() -> None:
    # Aligned framings, decent reliability, descriptive ask -> single pass.
    ev = [_ev("B", [1.0, 0.0], i=1), _ev("B", [0.99, 0.14], i=2), _ev("C", [0.98, 0.2], i=3)]
    mode, reason = decide_mode("What is happening at the disputed reef?", ev)
    assert mode == "quick"
    assert "single pass" in reason


def test_no_embeddings_defaults_quick_for_descriptive() -> None:
    # Divergence unknowable (no embeddings) and sourcing mixed -> don't over-escalate.
    mode, _ = decide_mode("Summarize the earthquake response", [_ev("B", i=1), _ev("D", i=2)])
    assert mode == "quick"
