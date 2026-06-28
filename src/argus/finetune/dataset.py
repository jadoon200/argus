"""Self-distillation dataset builder for MLX LoRA fine-tuning.

The strong teacher (qwen2.5:14b via the configured backend) generates ARGUS-style cited
briefs; we keep only the ones that pass the eval bar (cited + non-empty) and write them
as chat examples in the MLX-LM format. A small student then learns to one-shot what the
multi-agent panel deliberates — distilling the tradecraft into a fast local model.
See docs/FINETUNE.md.
"""

import json
import random
from pathlib import Path
from typing import Any

from argus.agent.analyst import generate_brief
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.personas import ARGUS_IDENTITY
from argus.agent.state import EvidenceItem, format_evidence
from argus.config import get_settings
from argus.eval.goldset import QUERIES, evidence_by_id
from argus.eval.metrics import citation_coverage
from argus.logging import configure_logging, get_logger

log = get_logger(__name__)

TRAIN_SYSTEM = (
    ARGUS_IDENTITY + "\n\nProduce the intelligence brief directly in these sections: KEY JUDGMENTS "
    "(each ending with its [E#] citation), CONFIDENCE, KEY ASSUMPTIONS, INDICATORS, "
    "ALTERNATIVES, INTELLIGENCE GAPS."
)


def to_chat_example(query: str, evidence_block: str, brief_body: str) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": TRAIN_SYSTEM},
            {"role": "user", "content": f"QUESTION: {query}\n\nEVIDENCE:\n{evidence_block}"},
            {"role": "assistant", "content": brief_body},
        ]
    }


def generate_examples(
    items: list[tuple[str, list[EvidenceItem]]],
    backend: LLMBackend | None,
    min_coverage: float = 1.0,
) -> list[dict[str, Any]]:
    """Run the teacher on each (query, evidence); keep eval-passing briefs as examples."""
    examples: list[dict[str, Any]] = []
    for query, evidence in items:
        brief = generate_brief(query, evidence=evidence, backend=backend, persist=False)
        if (
            brief.key_judgments
            and brief.citations
            and brief.body.strip()
            and citation_coverage(brief.key_judgments) >= min_coverage
        ):
            examples.append(to_chat_example(query, format_evidence(evidence), brief.body))
        else:
            log.warning("dropped_low_quality_example", query=query)
    return examples


def gold_items() -> list[tuple[str, list[EvidenceItem]]]:
    """Seed items from the gold set. Scale this up with your own (query, evidence) pairs
    (e.g. gathered from the ingested corpus) for a production-size fine-tune."""
    by_id = evidence_by_id()
    evidence = [by_id[doc_id] for doc_id in sorted(by_id)]
    return [(gold.query, evidence) for gold in QUERIES]


def write_jsonl(
    examples: list[dict[str, Any]], out_dir: Path, valid_frac: float = 0.2, seed: int = 0
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shuffled = list(examples)
    random.Random(seed).shuffle(shuffled)
    n_valid = max(1, int(len(shuffled) * valid_frac)) if len(shuffled) > 1 else 0
    valid, train = shuffled[:n_valid], shuffled[n_valid:]
    for name, rows in (("train", train), ("valid", valid)):
        with (out_dir / f"{name}.jsonl").open("w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    return {"train": len(train), "valid": len(valid)}


def main() -> None:
    configure_logging()
    settings = get_settings()
    examples = generate_examples(gold_items(), resolve_backend())
    stats = write_jsonl(examples, Path(settings.finetune_data_dir))
    log.info("finetune_dataset_built", directory=settings.finetune_data_dir, **stats)


if __name__ == "__main__":
    main()
