from pathlib import Path

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
    assert len(reports) == 3

    # Retrieval finds the labelled-relevant docs in this clean fixture corpus.
    assert all(r.recall == 1.0 for r in reports)
    # The template digest only cites real evidence -> no fabrication slips through.
    assert all(r.fabricated == [] for r in reports)
    # Every digest line carries its citation.
    assert all(r.coverage == 1.0 for r in reports)
    # Calibration: the digest never exceeds low confidence, so it can't breach the trap.
    assert all(not r.over_confident for r in reports)


def test_render_report_has_aggregates() -> None:
    md = render_report(evaluate(backend=None), "template")
    assert "mean recall@3" in md
    assert "fabrication attempts caught" in md
    assert "calibration trap breaches" in md


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
