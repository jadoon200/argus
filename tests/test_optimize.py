from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("dspy")  # the `optimize` extra; skip cleanly where it isn't installed

from argus.agent.state import EvidenceItem
from argus.optimize.compile import build_trainset
from argus.optimize.metric import brief_metric
from argus.optimize.program import BriefProgram
from argus.optimize.serve import load_program, optimized_brief


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


class _FakeProgram:
    """A compiled program stand-in: returns a canned prediction, so no LM/Ollama is hit."""

    def __call__(self, question: str, evidence: str) -> SimpleNamespace:
        return SimpleNamespace(
            key_judgments=["Escalation is likely [E1]", "Fabricated claim [E9]"],
            confidence="moderate",
        )


def test_optimized_brief_maps_output_and_drops_fabricated_citations() -> None:
    evidence = [EvidenceItem("reuters.com:1", "Naval patrols increase", "reuters.com", "B", 3)]
    result = optimized_brief("q?", evidence, program=_FakeProgram())
    assert result.backend == "dspy"
    assert result.confidence == "moderate"
    assert result.key_judgments[0].endswith("[E1]")
    # [E1] resolves to the real doc id; the out-of-range [E9] is dropped (resolvability).
    assert result.citations == ["reuters.com:1"]


def test_load_program_without_artifact_returns_unoptimized(tmp_path: Path) -> None:
    program = load_program(tmp_path / "missing.json")
    assert program is not None and hasattr(program, "generate")
