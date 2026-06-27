from argus.eval.run import evaluate, render_report


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
