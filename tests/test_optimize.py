from types import SimpleNamespace

from argus.optimize.compile import build_trainset
from argus.optimize.metric import brief_metric
from argus.optimize.program import BriefProgram


def test_metric_rewards_full_coverage() -> None:
    ex = SimpleNamespace(max_confidence=None)
    pred = SimpleNamespace(
        key_judgments=["judgment a [E1]", "judgment b [E2]"], confidence="moderate"
    )
    assert brief_metric(ex, pred) == 1.0


def test_metric_partial_coverage() -> None:
    ex = SimpleNamespace(max_confidence=None)
    pred = SimpleNamespace(key_judgments=["cited [E1]", "uncited"], confidence="low")
    assert brief_metric(ex, pred) == 0.5


def test_metric_zeroed_when_overconfident() -> None:
    # Calibration discipline: exceeding the gold confidence cap nulls the reward.
    ex = SimpleNamespace(max_confidence="low")
    pred = SimpleNamespace(key_judgments=["cited [E1]"], confidence="high")
    assert brief_metric(ex, pred) == 0.0


def test_build_trainset_labels_evidence() -> None:
    examples = build_trainset()
    assert len(examples) == 3
    for ex in examples:
        assert ex.question
        assert "[E1]" in ex.evidence  # evidence rendered with citation labels


def test_brief_program_constructs() -> None:
    program = BriefProgram()
    assert program.generate is not None
