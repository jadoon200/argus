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

from sqlalchemy.orm import Session

from argus.agent.analyst import gather_evidence, generate_brief
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.personas import ARGUS_IDENTITY
from argus.agent.state import EvidenceItem, format_evidence
from argus.config import get_settings
from argus.db.base import session_scope
from argus.eval.goldset import QUERIES, corpus_retrieved, evidence_by_id
from argus.eval.metrics import citation_coverage
from argus.logging import configure_logging, get_logger
from argus.nlp.retrieval import hybrid_search

log = get_logger(__name__)

# Curated analyst queries to harvest the ingested corpus for a larger, more diverse
# distillation set — the gold set alone is only a handful. Topics span the OSINT remit
# (state competition, conflict, security, economic statecraft, hybrid threats).
DISTILL_QUERIES: list[str] = [
    "What is driving tensions in the South China Sea?",
    "What is the current state of the conflict in Sudan?",
    "How are Western sanctions affecting Russia's economy?",
    "What is the security situation in the Sahel?",
    "What are the latest developments in cross-strait relations with Taiwan?",
    "What is happening with North Korea's missile program?",
    "How is the conflict in Gaza affecting regional stability?",
    "What are the drivers of instability in the Red Sea shipping lanes?",
    "What is the status of Iran's nuclear program negotiations?",
    "What cyber threats are being attributed to state actors?",
    "How is China expanding its influence in the Pacific Islands?",
    "What is the latest on Russia-Ukraine front-line developments?",
    "What are the regional security implications of the coup in Myanmar?",
    "How are critical-mineral supply chains becoming a geopolitical flashpoint?",
    "What disinformation campaigns are being reported around upcoming elections?",
    "What is driving migration flows across the Mediterranean?",
]

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


def gold_items(k: int = 4) -> list[tuple[str, list[EvidenceItem]]]:
    """Seed items: each gold query paired with its top-k *retrieved* evidence.

    Uses the same hybrid retrieval the agent uses at inference, so the [E#] labels in the
    training target match what the served student will actually see — not the whole corpus
    handed in at once (which made the training distribution diverge from inference)."""
    corpus = corpus_retrieved()
    by_id = evidence_by_id()
    items: list[tuple[str, list[EvidenceItem]]] = []
    for gold in QUERIES:
        ranked = hybrid_search(gold.query, corpus, None, top_k=k)
        items.append((gold.query, [by_id[doc_id] for doc_id, _ in ranked]))
    return items


def corpus_items(
    session: Session, queries: list[str] | None = None, k: int | None = None
) -> list[tuple[str, list[EvidenceItem]]]:
    """Harvest (query, retrieved-evidence) pairs from an ingested corpus — the way to
    scale the distillation set well past the gold seed. Skips queries that retrieve
    nothing (so an empty/thin corpus quietly contributes fewer, not broken, examples)."""
    qs = queries if queries is not None else DISTILL_QUERIES
    kk = k if k is not None else get_settings().brief_context_docs
    items: list[tuple[str, list[EvidenceItem]]] = []
    for query in qs:
        evidence = gather_evidence(session, query, kk)
        if evidence:
            items.append((query, evidence))
    return items


def build_items() -> list[tuple[str, list[EvidenceItem]]]:
    """The gold seed always, plus corpus-harvested items when an ingested corpus is
    reachable — so the builder scales automatically once `make ingest`/`make enrich` have
    populated the DB, and still runs (smaller) with no corpus at all."""
    items = gold_items()
    try:
        with session_scope() as session:
            harvested = corpus_items(session)
    except Exception as exc:  # no DB / unreachable -> gold seed only
        log.warning("corpus_unavailable_using_gold_only", error=str(exc))
        harvested = []
    log.info("distillation_items", gold=len(items), corpus=len(harvested))
    return items + harvested


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
    examples = generate_examples(build_items(), resolve_backend())
    stats = write_jsonl(examples, Path(settings.finetune_data_dir))
    log.info("finetune_dataset_built", directory=settings.finetune_data_dir, **stats)


if __name__ == "__main__":
    main()
