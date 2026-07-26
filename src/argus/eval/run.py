"""Run the eval harness and print a markdown report.

    python -m argus.eval.run

Retrieval metrics are deterministic (no LLM). Brief metrics use whatever backend is
available — local Ollama if running, else the deterministic template digest — so this
runs free, in CI included. The headline honesty checks are citation coverage,
fabrication attempts caught, and the calibration trap (does the agent overstate a
single low-reliability source?).
"""

from dataclasses import dataclass
from pathlib import Path

from argus.agent.analyst import generate_brief
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.state import evidence_labels
from argus.config import get_settings
from argus.eval.fusion import evaluate_routing
from argus.eval.goldset import QUERIES, corpus_retrieved, evidence_by_id
from argus.eval.judge import judge_brief
from argus.eval.metrics import (
    citation_coverage,
    citation_markers,
    exceeds_confidence,
    recall_at_k,
    reciprocal_rank,
)
from argus.eval.nli import NliScorer, agreement, load_nli_scorer, score_brief_nli
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
    # Reading-dependent (LLM-judge) metrics — None on the deterministic/template path.
    faithfulness: float | None = None
    citation_support: float | None = None
    # Deterministic, cross-family NLI metrics — None unless an NLI scorer is enabled.
    # Atomic = RAGAS-style claim decomposition; strict = whole-judgment entailment (experimental).
    nli_faithfulness: float | None = None
    nli_citation_support: float | None = None
    nli_strict_faithfulness: float | None = None
    nli_strict_citation_support: float | None = None


def evaluate(
    backend: LLMBackend | None,
    nli_scorer: NliScorer | None = None,
    nli_threshold: float = 0.5,
) -> list[QueryReport]:
    """Score the gold set. `backend=None` forces the deterministic template digest.

    An optional `nli_scorer` adds deterministic, cross-family faithfulness/citation numbers
    alongside the (stochastic, self-biased) LLM judge — the two are reported side by side."""
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

        faithfulness = citation_support = None
        if backend is not None and brief.key_judgments:  # LLM-judge only when a model is present
            judged = judge_brief(brief.key_judgments, evidence, backend)
            if judged.n:
                faithfulness, citation_support = judged.faithfulness, judged.citation_support

        nli_f = nli_cs = nli_sf = nli_scs = None
        if nli_scorer is not None and brief.key_judgments:  # deterministic NLI, when enabled
            kj = brief.key_judgments
            atomic = score_brief_nli(kj, evidence, nli_scorer, nli_threshold, decompose_claims=True)
            strict = score_brief_nli(
                kj, evidence, nli_scorer, nli_threshold, decompose_claims=False
            )
            if atomic.n:
                nli_f, nli_cs = atomic.faithfulness, atomic.citation_support
            if strict.n:
                nli_sf, nli_scs = strict.faithfulness, strict.citation_support

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
                faithfulness=faithfulness,
                citation_support=citation_support,
                nli_faithfulness=nli_f,
                nli_citation_support=nli_cs,
                nli_strict_faithfulness=nli_sf,
                nli_strict_citation_support=nli_scs,
            )
        )
    return reports


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _results_table(reports: list[QueryReport]) -> list[str]:
    """The per-query table + aggregate summary — shared by stdout and the EVAL.md block."""
    lines = [
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
    judged = [r for r in reports if r.faithfulness is not None]
    if judged:  # only when an LLM judge ran (a backend was available)
        support = [r.citation_support for r in judged if r.citation_support is not None]
        lines += [
            f"- **mean faithfulness (grounded claims, LLM-judge)**: "
            f"{_mean([r.faithfulness for r in judged if r.faithfulness is not None]):.2f}",
            f"- **mean citation support (cited evidence backs the claim, LLM-judge)**: "
            f"{_mean(support):.2f}",
        ]
    nli = [r for r in reports if r.nli_faithfulness is not None]
    if nli:  # deterministic + cross-family; atomic decomposition is the valid metric (see notes)
        af = [r.nli_faithfulness for r in nli if r.nli_faithfulness is not None]
        acs = [r.nli_citation_support for r in nli if r.nli_citation_support is not None]
        sf = [r.nli_strict_faithfulness for r in nli if r.nli_strict_faithfulness is not None]
        scs = [
            r.nli_strict_citation_support for r in nli if r.nli_strict_citation_support is not None
        ]
        lines += [
            f"- **mean NLI faithfulness (atomic claim decomposition, deterministic)**: "
            f"{_mean(af):.2f}",
            f"- **mean NLI citation support (atomic claim decomposition, deterministic)**: "
            f"{_mean(acs):.2f}",
            f"- **mean NLI faithfulness (strict whole-judgment entailment, experimental)**: "
            f"{_mean(sf):.2f}",
            f"- **mean NLI citation support (strict whole-judgment entailment, experimental)**: "
            f"{_mean(scs):.2f}",
        ]
    routing = evaluate_routing()
    lines += [
        f"- **fusion lane-routing precision ({routing.cases}-query labelled set)**: "
        f"{routing.precision:.2f}",
        f"- **fusion lane-routing recall ({routing.cases}-query labelled set)**: "
        f"{routing.recall:.2f}",
        f"- **fusion lane-routing exact match ({routing.cases}-query labelled set)**: "
        f"{routing.exact_match:.2f}",
    ]
    return lines


def render_report(reports: list[QueryReport], backend_name: str) -> str:
    header = [
        f"## ARGUS eval — backend: `{backend_name}`",
        "",
        f"Retrieval (recall@{EVAL_K}, MRR) is deterministic; brief metrics use the backend above.",
        "",
    ]
    return "\n".join(header + _results_table(reports))


# --- EVAL.md auto-recording ----------------------------------------------------------
# `make eval` rewrites the block between these markers so the recorded numbers are
# generated from the code, never hand-maintained (and never silently stale).
EVAL_DOC = Path(__file__).resolve().parents[3] / "docs" / "EVAL.md"
_BEGIN = "<!-- AUTOGEN:eval-results (regenerated by `make eval`; do not edit by hand) -->"
_END = "<!-- /AUTOGEN:eval-results -->"


def eval_doc_block(reports: list[QueryReport], backend_name: str) -> str:
    note = f"_Auto-recorded by `make eval` — backend `{backend_name}`._"
    return "\n".join([note, "", *_results_table(reports)])


def update_eval_doc(block: str, doc: Path = EVAL_DOC) -> bool:
    """Replace the AUTOGEN block in EVAL.md (creating it at the end if absent). Returns
    False if the doc doesn't exist, so a stray run never fabricates the file."""
    if not doc.exists():
        return False
    wrapped = f"{_BEGIN}\n{block}\n{_END}"
    text = doc.read_text()
    if _BEGIN in text and _END in text:
        text = text[: text.index(_BEGIN)] + wrapped + text[text.index(_END) + len(_END) :]
    else:
        text = text.rstrip() + "\n\n" + wrapped + "\n"
    doc.write_text(text)
    return True


def main() -> None:
    configure_logging()
    settings = get_settings()
    backend = resolve_backend()
    # NLI scoring is opt-in (the model downloads on first use), so CI never pulls it.
    nli_scorer = load_nli_scorer(settings.nli_model) if settings.nli_enabled else None
    if settings.nli_enabled and nli_scorer is not None:
        log.info("nli_judge_human_agreement", agreement=round(agreement(nli_scorer), 3))
    reports = evaluate(backend, nli_scorer, settings.nli_entailment_threshold)
    name = backend.name if backend else "template"
    print(render_report(reports, name))
    if update_eval_doc(eval_doc_block(reports, name)):
        log.info("eval_doc_updated", path=str(EVAL_DOC))


if __name__ == "__main__":
    main()
