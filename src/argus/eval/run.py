"""Run the eval harness and print a markdown report.

    python -m argus.eval.run

Retrieval metrics are deterministic (no LLM). Brief metrics use whatever backend is
available — local Ollama if running, else the deterministic template digest — so this
runs free, in CI included. The headline honesty checks are citation coverage,
fabrication attempts caught, and the calibration trap (does the agent overstate a
single low-reliability source?).
"""

from dataclasses import dataclass

from argus.agent.analyst import generate_brief
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.state import evidence_labels
from argus.eval.goldset import QUERIES, corpus_retrieved, evidence_by_id
from argus.eval.metrics import (
    citation_coverage,
    citation_markers,
    exceeds_confidence,
    recall_at_k,
    reciprocal_rank,
)
from argus.logging import configure_logging, get_logger
from argus.nlp.retrieval import hybrid_search

log = get_logger(__name__)

EVAL_K = 3  # small fixed corpus: judge retrieval on the top-3, and brief on top-3 evidence


@dataclass
class QueryReport:
    query: str
    recall: float
    rr: float
    confidence: str | None
    coverage: float
    n_citations: int
    fabricated: list[str]
    over_confident: bool


def evaluate(backend: LLMBackend | None) -> list[QueryReport]:
    """Score the gold set. `backend=None` forces the deterministic template digest."""
    corpus = corpus_retrieved()
    by_id = evidence_by_id()
    reports: list[QueryReport] = []

    for gold in QUERIES:
        ranked = hybrid_search(gold.query, corpus, None, top_k=len(corpus))
        retrieved_ids = [doc_id for doc_id, _ in ranked]
        evidence = [by_id[doc_id] for doc_id, _ in ranked[:EVAL_K]]

        brief = generate_brief(gold.query, evidence=evidence, backend=backend, persist=False)
        valid = set(evidence_labels(evidence)) | {e.doc_id for e in evidence}
        fabricated = sorted({m for m in citation_markers(brief.body) if m not in valid})

        reports.append(
            QueryReport(
                query=gold.query,
                recall=recall_at_k(retrieved_ids, gold.relevant_ids, EVAL_K),
                rr=reciprocal_rank(retrieved_ids, gold.relevant_ids),
                confidence=brief.confidence,
                coverage=citation_coverage(brief.key_judgments),
                n_citations=len(brief.citations),
                fabricated=fabricated,
                over_confident=exceeds_confidence(brief.confidence, gold.max_confidence),
            )
        )
    return reports


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def render_report(reports: list[QueryReport], backend_name: str) -> str:
    lines = [
        f"## ARGUS eval — backend: `{backend_name}`",
        "",
        f"Retrieval (recall@{EVAL_K}, MRR) is deterministic; brief metrics use the backend above.",
        "",
        "| Query | recall@k | MRR | confidence | cite-coverage | citations | fabricated |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        flag = " ⚠️OVER" if r.over_confident else ""
        lines.append(
            f"| {r.query[:42]} | {r.recall:.2f} | {r.rr:.2f} | {r.confidence or '—'}{flag} "
            f"| {r.coverage:.2f} | {r.n_citations} | {len(r.fabricated)} |"
        )
    lines += [
        "",
        f"- **mean recall@{EVAL_K}**: {_mean([r.recall for r in reports]):.2f}",
        f"- **mean MRR**: {_mean([r.rr for r in reports]):.2f}",
        f"- **mean citation coverage**: {_mean([r.coverage for r in reports]):.2f}",
        f"- **fabrication attempts caught (dropped)**: {sum(len(r.fabricated) for r in reports)}",
        f"- **calibration trap breaches**: {sum(1 for r in reports if r.over_confident)} "
        "(brief exceeded the confidence a single low-reliability source warrants)",
    ]
    return "\n".join(lines)


def main() -> None:
    configure_logging()
    backend = resolve_backend()
    reports = evaluate(backend)
    print(render_report(reports, backend.name if backend else "template"))


if __name__ == "__main__":
    main()
