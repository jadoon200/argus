"""Compile (optimize) the brief program against the eval metric.

    python -m argus.optimize.compile        # make optimize

Runs the local Ollama model many times to bootstrap good few-shot demonstrations —
slow, and offline. The optimized program is saved to an artifact that the agent can
later load. Requires the `optimize` extra (`pip install -e .[optimize]`).
"""

from pathlib import Path
from typing import Any

import dspy

from argus.agent.state import format_evidence
from argus.eval.goldset import QUERIES, evidence_by_id
from argus.logging import configure_logging, get_logger
from argus.optimize.metric import brief_metric
from argus.optimize.program import BriefProgram, configure_lm

log = get_logger(__name__)

ARTIFACT = Path("data/dspy/optimized_brief.json")


def build_trainset() -> list[Any]:
    """Gold queries → DSPy examples (question + labelled evidence + the confidence cap)."""
    by_id = evidence_by_id()
    examples: list[Any] = []
    for gold in QUERIES:
        evidence = format_evidence([by_id[doc_id] for doc_id in sorted(gold.relevant_ids)])
        examples.append(
            dspy.Example(
                question=gold.query,
                evidence=evidence,
                max_confidence=gold.max_confidence,
            ).with_inputs("question", "evidence")
        )
    return examples


def main() -> None:
    configure_logging()
    configure_lm()
    optimizer = dspy.BootstrapFewShot(
        metric=brief_metric, max_bootstrapped_demos=2, max_labeled_demos=2
    )
    compiled = optimizer.compile(BriefProgram(), trainset=build_trainset())
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    compiled.save(str(ARTIFACT))
    log.info("optimized_program_saved", path=str(ARTIFACT))


if __name__ == "__main__":
    main()
