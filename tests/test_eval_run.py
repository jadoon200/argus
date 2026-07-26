from pathlib import Path

from argus.eval.goldset import QUERIES
from argus.eval.run import (
    _BEGIN,
    _END,
    eval_doc_block,
    evaluate,
    render_report,
    update_eval_doc,
)


def test_evaluate_template_path_is_deterministic() -> None:
    reports = evaluate(backend=None)  # None forces the deterministic template digest
    assert len(reports) == len(QUERIES)

    # Retrieval finds the labelled-relevant docs among the (now 20-doc) fixture corpus.
    assert all(r.recall == 1.0 for r in reports)
    # The template digest only cites real evidence -> no fabrication slips through.
    assert all(r.fabricated == [] for r in reports)
    # Every digest line carries its citation.
    assert all(r.coverage == 1.0 for r in reports)
    # Calibration: the digest never exceeds low confidence, so it can't breach the trap.
    assert all(not r.over_confident for r in reports)


def test_goldset_is_a_meaningful_size_with_calibration_coverage() -> None:
    # The set was deliberately expanded so the LLM-path means are less run-to-run noise.
    assert len(QUERIES) >= 10
    # Several calibration traps/contested caps, not just one, so the calibration metric is
    # measured over multiple cases rather than a single lucky (or unlucky) draw.
    capped = [q for q in QUERIES if q.max_confidence is not None]
    assert len(capped) >= 4


def test_render_report_has_aggregates() -> None:
    md = render_report(evaluate(backend=None), "template")
    assert "mean recall@3" in md
    assert "fabrication attempts caught" in md
    assert "calibration trap breaches" in md
    assert "fusion lane-routing precision" in md
    assert "fusion lane-routing exact match" in md


def test_update_eval_doc_replaces_only_the_managed_block(tmp_path: Path) -> None:
    doc = tmp_path / "EVAL.md"
    doc.write_text(f"# Eval\n\nkeep before\n\n{_BEGIN}\nstale numbers\n{_END}\n\nkeep after\n")

    block = eval_doc_block(evaluate(backend=None), "template")
    assert update_eval_doc(block, doc=doc) is True

    text = doc.read_text()
    assert "keep before" in text and "keep after" in text  # surrounding prose untouched
    assert "stale numbers" not in text  # old block replaced
    assert "mean recall@3" in text and text.count(_BEGIN) == 1  # exactly one fresh block


def test_update_eval_doc_noops_when_doc_missing(tmp_path: Path) -> None:
    # A stray run must never fabricate the doc.
    assert update_eval_doc("x", doc=tmp_path / "nope.md") is False
