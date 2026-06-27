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
from argus.agent.state import BriefResult, DeliberationState, EvidenceItem, evidence_labels
from argus.config import get_settings
from argus.db.base import session_scope
from argus.db.models import Brief, Document, Source
from argus.logging import configure_logging, get_logger
from argus.nlp.embed import embed_text
from argus.nlp.retrieval import RetrievedDoc, hybrid_search

log = get_logger(__name__)

_AUTO: object = object()  # sentinel: resolve the backend from settings
_CITATION_RE = re.compile(r"\[([^\]]+)\]")
_SECTION_HEADERS = ("KEY JUDGMENTS", "CONFIDENCE", "ALTERNATIVES", "INTELLIGENCE GAPS")
_CONFIDENCE_RE = re.compile(r"\b(low|moderate|high)\b", re.IGNORECASE)


def _doc_text(doc: Document) -> str:
    return f"{doc.title}. {doc.summary}" if doc.summary else doc.title


def gather_evidence(session: Session, query: str, k: int) -> list[EvidenceItem]:
    """Retrieve the top-k most relevant documents as rated evidence items."""
    docs = list(session.scalars(select(Document)).all())
    if not docs:
        return []
    has_embeddings = any(d.embedding for d in docs)
    rdocs = [RetrievedDoc(d.doc_id, _doc_text(d), d.embedding) for d in docs]
    query_vec = embed_text(query) if has_embeddings else None
    ranked = hybrid_search(query, rdocs, query_vec, top_k=k)

    by_id = {d.doc_id: d for d in docs}
    items: list[EvidenceItem] = []
    for doc_id, _ in ranked:
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


def _resolve_citations(text: str, label_map: dict[str, str]) -> list[str]:
    """Resolve [E#] labels (or a raw doc id) to doc ids, keeping only ones that exist.

    This is the citation-resolvability invariant: anything the model cites that doesn't
    map to a real evidence item is silently dropped, so a brief can never carry a
    fabricated citation.
    """
    valid_ids = set(label_map.values())
    out: list[str] = []
    for inner in _CITATION_RE.findall(text):
        for token in re.split(r"[,\s]+", inner.strip()):
            doc_id = label_map.get(token) or (token if token in valid_ids else None)
            if doc_id and doc_id not in out:
                out.append(doc_id)
    return out


def _assemble(
    query: str, evidence: list[EvidenceItem], state: DeliberationState, backend: str
) -> BriefResult:
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
        citations=_resolve_citations(finding, evidence_labels(evidence)),
        hypotheses=state.get("hypotheses", []),
        backend=backend,
    )


def extractive_brief(query: str, evidence: list[EvidenceItem]) -> BriefResult:
    """Deterministic, no-LLM fallback — an evidence digest, honestly labelled as such."""
    top = evidence[:8]
    sources = {e.source for e in evidence}
    body = "\n".join(
        [f"Evidence digest for: {query}", ""]
        + [f"- {e.rating()} {e.source}: {e.title} [{e.doc_id}]" for e in top]
    )
    return BriefResult(
        query=query,
        body=body,
        key_judgments=[f"{e.title} [{e.doc_id}]" for e in evidence[:3]],
        confidence="moderate" if len(sources) >= 3 else "low",
        gaps=(
            "Produced by the deterministic fallback (no LLM available): a relevance-ranked "
            "evidence digest, not an analytic judgment. Run with Ollama or Claude for a "
            "deliberated assessment."
        ),
        citations=[e.doc_id for e in top],
        backend="template",
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

    resolved = resolve_backend() if backend is _AUTO else cast(LLMBackend | None, backend)
    if resolved is None:
        result = extractive_brief(query, evidence)
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
