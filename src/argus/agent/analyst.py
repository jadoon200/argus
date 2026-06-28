"""ARGUS analyst — turn a question into a cited intelligence brief.

    python -m argus.agent.analyst "What is driving tensions in the South China Sea?"

Gathers evidence by hybrid retrieval, runs the multi-agent deliberation (or, with no
LLM available, a clearly-labelled deterministic evidence digest), then assembles the
brief and enforces the citation invariant: every cited id must resolve to a real piece
of retrieved evidence — fabricated citations are dropped, never shown.
"""

import re
import sys
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.agent.graph import run_deliberation
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.personas import ONESHOT_SYSTEM
from argus.agent.schemas import Finding
from argus.agent.state import (
    BriefResult,
    DeliberationState,
    EvidenceItem,
    evidence_labels,
    format_evidence,
)
from argus.bridge.sentinel import cyber_evidence
from argus.config import get_settings
from argus.db.base import session_scope
from argus.db.models import Brief, Document, Source
from argus.logging import configure_logging, get_logger
from argus.nlp.embed import embed_text
from argus.nlp.retrieval import RetrievedDoc, hybrid_search

log = get_logger(__name__)

_AUTO: object = object()  # sentinel: resolve the backend from settings
_CITATION_RE = re.compile(r"\[([^\]]+)\]")
_LABEL_NUM_RE = re.compile(r"\d+")
_SECTION_HEADERS = ("KEY JUDGMENTS", "CONFIDENCE", "ALTERNATIVES", "INTELLIGENCE GAPS")
_CONFIDENCE_RE = re.compile(r"\b(low|moderate|high)\b", re.IGNORECASE)


def _doc_text(doc: Document) -> str:
    return f"{doc.title}. {doc.summary}" if doc.summary else doc.title


def _select_diverse(
    ranked: list[tuple[str, float]], source_of: dict[str, str], max_per_source: int, k: int
) -> list[str]:
    """Pick up to `k` doc ids in rank order, capping each source at `max_per_source` so one
    prolific outlet can't dominate; backfill from the capped-out remainder if needed."""
    if max_per_source <= 0:
        return [doc_id for doc_id, _ in ranked[:k]]
    chosen: list[str] = []
    deferred: list[str] = []
    per_source: dict[str, int] = {}
    for doc_id, _ in ranked:
        src = source_of[doc_id]
        if per_source.get(src, 0) < max_per_source:
            chosen.append(doc_id)
            per_source[src] = per_source.get(src, 0) + 1
        else:
            deferred.append(doc_id)
        if len(chosen) >= k:
            return chosen
    for doc_id in deferred:  # too few distinct sources — fill the rest, best-ranked first
        if len(chosen) >= k:
            break
        chosen.append(doc_id)
    return chosen


def gather_evidence(
    session: Session, query: str, k: int, max_per_source: int | None = None
) -> list[EvidenceItem]:
    """Retrieve the top-k most relevant documents as rated evidence items, with a
    per-source diversity cap so no single outlet dominates the agents' evidence."""
    docs = list(session.scalars(select(Document)).all())
    if not docs:
        return []
    cap = max_per_source if max_per_source is not None else get_settings().brief_max_per_source
    has_embeddings = any(d.embedding for d in docs)
    rdocs = [RetrievedDoc(d.doc_id, _doc_text(d), d.embedding) for d in docs]
    query_vec = None
    if has_embeddings:
        try:
            query_vec = embed_text(query)
        except ImportError:
            # Slim deployments ship without sentence-transformers — degrade to BM25.
            log.warning("embeddings_unavailable_lexical_only")
    by_id = {d.doc_id: d for d in docs}
    ranked = hybrid_search(query, rdocs, query_vec, top_k=len(rdocs))
    selected = _select_diverse(ranked, {d.doc_id: d.source for d in docs}, cap, k)

    items: list[EvidenceItem] = []
    for doc_id in selected:
        doc = by_id[doc_id]
        src = session.get(Source, doc.source)
        items.append(
            EvidenceItem(
                doc_id=doc.doc_id,
                title=doc.title,
                source=doc.source,
                reliability=src.reliability if src else "F",
                credibility=doc.credibility,
                summary=doc.summary,
                published=doc.published.date().isoformat() if doc.published else None,
                url=doc.url,
            )
        )
    return items


def _match_header(line: str) -> str | None:
    upper = line.upper()
    for header in _SECTION_HEADERS:
        if upper.startswith(header):
            return header
    return None


def _parse_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {h: [] for h in _SECTION_HEADERS}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        header = _match_header(line)
        if header:
            current = header
            rest = line[len(header) :].lstrip(":").strip()
            if rest:
                sections[current].append(rest)
        elif current and line:
            sections[current].append(line)
    return sections


def _strip_bullet(line: str) -> str:
    return line.lstrip("-*•· ").strip()


def _resolve_label(token: str, label_map: dict[str, str], valid_ids: set[str]) -> str | None:
    """Map one citation token to a real doc id, tolerating label variants.

    Models cite inconsistently — `E1`, `1`, `[E1]`, even the raw doc id. We accept a
    raw doc id, the exact label, or any token carrying the label's number (so `1` and
    `E1` both resolve to E1). Anything that still doesn't map returns None and is
    dropped — the citation-resolvability invariant: a brief never carries a fabrication.
    """
    token = token.strip()
    if token in valid_ids:
        return token
    if token in label_map:
        return label_map[token]
    match = _LABEL_NUM_RE.search(token)
    return label_map.get(f"E{int(match.group())}") if match else None


def _resolve_citations(text: str, label_map: dict[str, str]) -> list[str]:
    valid_ids = set(label_map.values())
    out: list[str] = []
    for inner in _CITATION_RE.findall(text):
        for token in re.split(r"[,\s]+", inner.strip()):
            doc_id = _resolve_label(token, label_map, valid_ids)
            if doc_id and doc_id not in out:
                out.append(doc_id)
    return out


def _assemble(
    query: str, evidence: list[EvidenceItem], state: DeliberationState, backend: str
) -> BriefResult:
    label_map = evidence_labels(evidence)
    struct = state.get("finding_struct")
    if struct is not None:
        return _assemble_from_struct(query, struct, label_map, state, backend)

    finding = state.get("finding", "")
    sections = _parse_sections(finding)
    confidence_text = " ".join(sections["CONFIDENCE"])
    confidence_match = _CONFIDENCE_RE.search(confidence_text)
    return BriefResult(
        query=query,
        body=finding,
        key_judgments=[_strip_bullet(line) for line in sections["KEY JUDGMENTS"]],
        confidence=confidence_match.group(1).lower() if confidence_match else None,
        alternatives=" ".join(sections["ALTERNATIVES"]) or None,
        gaps=" ".join(sections["INTELLIGENCE GAPS"]) or None,
        citations=_resolve_citations(finding, label_map),
        hypotheses=state.get("hypotheses", []),
        ach_ranking=state.get("ach_ranking", []),
        backend=backend,
    )


def _assemble_from_struct(
    query: str,
    struct: "Finding",
    label_map: dict[str, str],
    state: DeliberationState,
    backend: str,
) -> BriefResult:
    """Build the brief from the validated structured finding (the reliable path)."""
    valid_ids = set(label_map.values())
    citations: list[str] = []
    for kj in struct.key_judgments:
        for label in kj.citations:
            doc_id = _resolve_label(label, label_map, valid_ids)
            if doc_id and doc_id not in citations:
                citations.append(doc_id)
    # Also pick up citations elsewhere in the finding (e.g. the alternative hypothesis).
    for doc_id in _resolve_citations(state.get("finding", ""), label_map):
        if doc_id not in citations:
            citations.append(doc_id)
    key_judgments = [
        f"{kj.judgment} {' '.join(f'[{c}]' for c in kj.citations)}".rstrip()
        for kj in struct.key_judgments
    ]
    alternatives = struct.alternative_hypothesis or None
    if alternatives and struct.collection_requirement:
        alternatives = f"{alternatives} Collection requirement: {struct.collection_requirement}"
    return BriefResult(
        query=query,
        body=state.get("finding", ""),
        key_judgments=key_judgments,
        confidence=struct.confidence,
        key_assumptions=struct.key_assumptions,
        indicators=struct.indicators,
        alternatives=alternatives,
        gaps="; ".join(struct.intelligence_gaps) or None,
        citations=citations,
        hypotheses=state.get("hypotheses", []),
        ach_ranking=state.get("ach_ranking", []),
        critique_response=struct.critique_response or None,
        backend=backend,
    )


def extractive_brief(query: str, evidence: list[EvidenceItem]) -> BriefResult:
    """Deterministic, no-LLM fallback — an evidence digest, honestly labelled as such."""
    top = evidence[:8]
    body = "\n".join(
        [f"Evidence digest for: {query}", ""]
        + [f"- {e.rating()} {e.source}: {e.title} [{e.doc_id}]" for e in top]
    )
    return BriefResult(
        query=query,
        body=body,
        key_judgments=[f"{e.title} [{e.doc_id}]" for e in evidence[:3]],
        # A digest is not an assessment — it never claims more than low confidence.
        confidence="low",
        gaps=(
            "Produced by the deterministic fallback (no LLM available): a relevance-ranked "
            "evidence digest, not an analytic judgment. Run with Ollama or Claude for a "
            "deliberated assessment."
        ),
        citations=[e.doc_id for e in top],
        backend="template",
    )


def oneshot_brief(query: str, evidence: list[EvidenceItem], backend: LLMBackend) -> BriefResult:
    """A single-shot brief from `backend` — the fine-tuned student's intended mode. One LLM
    call with the *same* prompt the student was trained on (`ONESHOT_SYSTEM`), parsed into a
    cited brief and held to the same resolvability invariant (fabricated labels dropped)."""
    user = f"QUESTION: {query}\n\nEVIDENCE:\n{format_evidence(evidence)}"
    text = backend.complete(ONESHOT_SYSTEM, user)
    sections = _parse_sections(text)
    label_map = evidence_labels(evidence)
    confidence_match = _CONFIDENCE_RE.search(" ".join(sections["CONFIDENCE"]))
    return BriefResult(
        query=query,
        body=text,
        key_judgments=[_strip_bullet(line) for line in sections["KEY JUDGMENTS"]],
        confidence=confidence_match.group(1).lower() if confidence_match else None,
        alternatives=" ".join(sections["ALTERNATIVES"]) or None,
        gaps=" ".join(sections["INTELLIGENCE GAPS"]) or None,
        citations=_resolve_citations(text, label_map),
        backend=backend.name,
    )


def generate_brief(
    query: str,
    *,
    session: Session | None = None,
    evidence: list[EvidenceItem] | None = None,
    backend: LLMBackend | None | object = _AUTO,
    persist: bool = True,
) -> BriefResult:
    """Produce a cited brief. `backend=_AUTO` resolves from settings (free by default);
    pass an explicit backend (or None to force the deterministic digest)."""
    if evidence is None:
        if session is None:
            raise ValueError("generate_brief needs either `evidence` or a `session`")
        evidence = gather_evidence(session, query, get_settings().brief_context_docs)
        # All-source fusion: append cyber campaigns from SENTINEL when the bridge is on
        # (no-op by default). Cyber items become citable evidence alongside the news.
        evidence = evidence + cyber_evidence()

    mode = get_settings().brief_mode
    if backend is _AUTO and mode == "dspy":
        # Optimized single-shot path. Lazy import: the `optimize` extra (DSPy) must not be
        # a hard dependency of the core serving flow.
        from argus.optimize.serve import optimized_brief

        result = optimized_brief(query, evidence)
    else:
        resolved = resolve_backend() if backend is _AUTO else cast(LLMBackend | None, backend)
        if resolved is None:
            result = extractive_brief(query, evidence)
        elif mode == "student":
            # One-shot the brief from the backend (the distilled student's intended use),
            # instead of running it through the multi-agent panel it wasn't trained for.
            result = oneshot_brief(query, evidence, resolved)
        else:
            state = run_deliberation(query, evidence, resolved)
            result = _assemble(query, evidence, state, resolved.name)

    if persist and session is not None:
        session.add(
            Brief(
                query=result.query,
                body=result.body,
                key_judgments=result.key_judgments or None,
                citations=result.citations or None,
                confidence=result.confidence,
                backend=result.backend,
            )
        )
    log.info(
        "brief_generated",
        backend=result.backend,
        judgments=len(result.key_judgments),
        citations=len(result.citations),
    )
    return result


def render(result: BriefResult) -> str:
    lines = [
        "═" * 70,
        f"ARGUS INTELLIGENCE BRIEF   (engine: {result.backend})",
        f"Q: {result.query}",
        "═" * 70,
        "",
        "KEY JUDGMENTS",
    ]
    lines += [f"  • {kj}" for kj in (result.key_judgments or ["(none)"])]
    lines += ["", f"CONFIDENCE: {result.confidence or 'n/a'}"]
    if result.ach_ranking:
        lines += ["", "COMPETING HYPOTHESES (ACH — least-disconfirmed first)"]
        lines += [
            f"  {i + 1}. {s.hypothesis}  (disconfirm={s.inconsistency:.2f})"
            for i, s in enumerate(result.ach_ranking)
        ]
    if result.critique_response:
        lines += ["", f"RED TEAM RESPONSE: {result.critique_response}"]
    if result.key_assumptions:
        lines += ["", "KEY ASSUMPTIONS"]
        lines += [f"  • {a}" for a in result.key_assumptions]
    if result.indicators:
        lines += ["", "INDICATORS & WARNINGS"]
        lines += [f"  • {i}" for i in result.indicators]
    if result.alternatives:
        lines += ["", f"ALTERNATIVE HYPOTHESIS: {result.alternatives}"]
    if result.gaps:
        lines += ["", f"INTELLIGENCE GAPS: {result.gaps}"]
    cites = ", ".join(result.citations) or "(none)"
    lines += ["", f"CITATIONS ({len(result.citations)}): {cites}"]
    return "\n".join(lines)


if __name__ == "__main__":
    configure_logging()
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python -m argus.agent.analyst "<question>"')
        raise SystemExit(2)
    with session_scope() as db:
        brief = generate_brief(question, session=db)
    print(render(brief))
