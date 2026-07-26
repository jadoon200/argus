"""Serve a brief from the DSPy-compiled program — the optimized single-shot path.

`make optimize` compiles a few-shot prompt against the eval metric and saves it to
`data/dspy/`. Until now nothing loaded that artifact, so the optimization never reached a
served brief. This module loads the compiled program and turns its output into a proper,
citation-checked `BriefResult` — the fast, optimized alternative to the multi-agent panel
(reached via `ARGUS_BRIEF_MODE=dspy` or `make brief-dspy`). Like every ARGUS path, it
enforces citation resolvability: only `[E#]` labels that resolve to real evidence survive.
"""

import sys
from pathlib import Path

from argus.agent.analyst import _resolve_citations
from argus.agent.state import (
    BriefResult,
    EvidenceItem,
    deduplicate_evidence,
    evidence_labels,
    format_evidence,
)
from argus.logging import configure_logging, get_logger
from argus.optimize.program import BriefProgram, configure_lm

log = get_logger(__name__)

ARTIFACT = Path("data/dspy/optimized_brief.json")
_CONFIDENCE = {"low", "moderate", "high"}


def load_program(path: Path = ARTIFACT) -> BriefProgram:
    """The compiled program if the artifact exists, else an unoptimized one (so serving
    still works before `make optimize` has been run — just without the tuned prompt)."""
    program = BriefProgram()
    if path.exists():
        program.load(str(path))
        log.info("loaded_optimized_program", path=str(path))
    else:
        log.warning("optimized_program_missing_using_unoptimized", path=str(path))
    return program


def optimized_brief(
    query: str, evidence: list[EvidenceItem], program: BriefProgram | None = None
) -> BriefResult:
    """Run the compiled DSPy program for `query` over `evidence` into a cited brief."""
    evidence = deduplicate_evidence(evidence)
    if program is None:
        configure_lm()
        program = load_program()
    prediction = program(question=query, evidence=format_evidence(evidence))

    judgments = [
        str(j).strip() for j in (getattr(prediction, "key_judgments", []) or []) if str(j).strip()
    ]
    confidence = str(getattr(prediction, "confidence", "") or "").strip().lower()
    label_map = evidence_labels(evidence)
    body = "\n".join(f"- {j}" for j in judgments)
    return BriefResult(
        query=query,
        body=body,
        key_judgments=judgments,
        confidence=confidence if confidence in _CONFIDENCE else None,
        citations=_resolve_citations(body, label_map),  # fabricated labels dropped
        backend="dspy",
    )


def main() -> None:
    configure_logging()
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python -m argus.optimize.serve "<question>"')
        raise SystemExit(2)
    from argus.agent.analyst import gather_evidence, render
    from argus.config import get_settings
    from argus.db.base import session_scope

    with session_scope() as db:
        evidence = gather_evidence(db, question, get_settings().brief_context_docs)
    print(render(optimized_brief(question, evidence)))


if __name__ == "__main__":
    main()
