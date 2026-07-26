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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus.agent.calibration import apply_confidence_cap
from argus.agent.graph import run_deliberation
from argus.agent.llm import LLMBackend, resolve_backend
from argus.agent.personas import ONESHOT_SYSTEM
from argus.agent.router import decide_mode
from argus.agent.schemas import Finding
from argus.agent.state import (
    BriefResult,
    DeliberationState,
    EvidenceItem,
    deduplicate_evidence,
    evidence_labels,
    format_evidence,
)
from argus.agent.triage import (
    capabilities_brief,
    is_meta_query,
    no_reporting_brief,
    relevant_count,
)
from argus.agent.workers import gather_fused_evidence
from argus.collection.ondemand import collect_for_query
from argus.config import get_settings
from argus.db.base import session_scope
from argus.db.models import Brief, Document, Source
from argus.logging import configure_logging, get_logger
from argus.nlp.embed import embed_text
from argus.nlp.fulltext import hydrate_documents, needs_text, reembed_documents
from argus.nlp.retrieval import RetrievedDoc, hybrid_search

log = get_logger(__name__)

_AUTO: object = object()  # sentinel: resolve the backend from settings
_CITATION_RE = re.compile(r"\[([^\]]+)\]")
_LABEL_NUM_RE = re.compile(r"\d+")
_SECTION_HEADERS = (
    "KEY JUDGMENTS",
    "CONFIDENCE",
    "KEY ASSUMPTIONS",  # Key Assumptions Check — dropped before this was parsed
    "INDICATORS",  # Indicators & Warnings — dropped before this was parsed
    "ALTERNATIVES",
    "INTELLIGENCE GAPS",
)
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

    # Backstop hydration: any headline-only doc that made the evidence cut gets its article
    # text fetched now — the analyst must reason over content, not titles. Best-effort.
    to_hydrate = [by_id[doc_id] for doc_id in selected if needs_text(by_id[doc_id])]
    if to_hydrate and hydrate_documents(to_hydrate):
        reembed_documents(to_hydrate)
        session.flush()

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
                embedding=doc.embedding,  # carried for divergence-based effort routing
            )
        )
    # Hybrid search always has a least-irrelevant result. Do not expose that noise through
    # /retrieve or the OSINT worker: retain only items with a real subject-token overlap.
    # Subject-less follow-ups keep everything by the triage contract.
    return [item for item in items if relevant_count(query, [item]) > 0]


_SIBLING_EVIDENCE_SOURCES = frozenset({"sky-geoint", "ocean-geoint", "sentinel-cyber"})


def _fused_relevant_count(query: str, evidence: list[EvidenceItem]) -> int:
    """Coverage count after supervisor routing.

    A routed sibling may deliberately return its top salient incidents for a domain-level or
    source-scoped question whose wording does not overlap a specific incident title. Those
    items are relevant by the supervisor/worker contract even when the generic OSINT token gate
    cannot see the relationship (for example, ``from PHAROS`` vs an ``AIS spoofing`` card).
    """
    return sum(
        1
        for item in evidence
        if item.source in _SIBLING_EVIDENCE_SOURCES or relevant_count(query, [item]) > 0
    )


def _match_header(line: str) -> str | None:
    # Models decorate headers ("**KEY JUDGMENTS:**", "## Key Judgments") — strip the
    # markdown dressing before matching, so a styled header still parses as a section.
    upper = line.upper().lstrip("#* ").rstrip()
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
            # Slice from the *undecorated* line so "**KEY JUDGMENTS:** text" keeps "text".
            plain = line.lstrip("#* ")
            rest = plain[len(header) :].strip(":*# ").strip()
            if rest:
                sections[current].append(rest)
        elif current and line:
            sections[current].append(line)
    return sections


def _strip_bullet(line: str) -> str:
    return line.lstrip("-*•· ").strip()


_CITE_SHAPED_RE = re.compile(r"^[Ee]?\d+$")  # E1, e1, or a bare 1 (bracket-stripped)
_EXPLICIT_LABEL_RE = re.compile(r"^[Ee]\d+$")  # E1 / e1 only — an unambiguous label


def _resolve_label(token: str, label_map: dict[str, str], valid_ids: set[str]) -> str | None:
    """Map one citation-array token to a real doc id, tolerating label variants.

    For the *structured* path, where the model put the token in a dedicated citations
    array: `E1`, `1`, `[E1]`, or the raw doc id all resolve. Anything that doesn't map
    returns None and is dropped — the resolvability invariant: no fabricated citation.
    """
    token = token.strip()
    if token in valid_ids:
        return token
    if token in label_map:
        return label_map[token]
    match = _LABEL_NUM_RE.search(token)
    return label_map.get(f"E{int(match.group())}") if match else None


def _resolve_explicit(token: str, label_map: dict[str, str], valid_ids: set[str]) -> str | None:
    """Resolve only *unambiguous* references — a raw doc id or an `E#`-prefixed label —
    never a bare number, which in prose is ambiguous (`[2 vessels]` is not a citation)."""
    token = token.strip()
    if token in valid_ids:
        return token
    if token in label_map:
        return label_map[token]
    match = _EXPLICIT_LABEL_RE.match(token)
    return label_map.get(f"E{int(match.group()[1:])}") if match else None


def _resolve_citations(text: str, label_map: dict[str, str]) -> list[str]:
    """Extract citations from free text. A bracket resolves bare numbers as labels only
    when it is a *pure* citation list (every token is a label/number/doc id) — so `[1, 2]`
    cites E1/E2, but `[2 vessels]` cites nothing (only explicit `E#`/doc ids survive there)."""
    valid_ids = set(label_map.values())
    out: list[str] = []
    for inner in _CITATION_RE.findall(text):
        tokens = [t for t in re.split(r"[,;\s]+", inner.strip()) if t]
        pure = bool(tokens) and all(t in valid_ids or _CITE_SHAPED_RE.match(t) for t in tokens)
        resolve = _resolve_label if pure else _resolve_explicit
        for token in tokens:
            doc_id = resolve(token, label_map, valid_ids)
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
        key_assumptions=[_strip_bullet(line) for line in sections["KEY ASSUMPTIONS"]],
        indicators=[_strip_bullet(line) for line in sections["INDICATORS"]],
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
        key_assumptions=[_strip_bullet(line) for line in sections["KEY ASSUMPTIONS"]],
        indicators=[_strip_bullet(line) for line in sections["INDICATORS"]],
        alternatives=" ".join(sections["ALTERNATIVES"]) or None,
        gaps=" ".join(sections["INTELLIGENCE GAPS"]) or None,
        citations=_resolve_citations(text, label_map),
        backend=backend.name,
    )


def to_brief_row(result: BriefResult) -> Brief:
    """Map a BriefResult onto a persistable Brief row — the FULL structured product
    (tradecraft sections included), so the dashboard never has to re-parse the body."""
    return Brief(
        query=result.query,
        body=result.body,
        key_judgments=result.key_judgments or None,
        citations=result.citations or None,
        confidence=result.confidence,
        key_assumptions=result.key_assumptions or None,
        indicators=result.indicators or None,
        hypotheses=result.hypotheses or None,
        ach_ranking=[
            {
                "hypothesis": h.hypothesis,
                "inconsistency": h.inconsistency,
                "consistent": h.consistent,
                "inconsistent": h.inconsistent,
            }
            for h in result.ach_ranking
        ]
        or None,
        alternatives=result.alternatives,
        gaps=result.gaps,
        critique_response=result.critique_response,
        backend=result.backend,
    )


def _deliberate_or_digest(
    query: str, evidence: list[EvidenceItem], backend: LLMBackend
) -> BriefResult:
    """Run the multi-agent panel, with the deterministic digest as a hard backstop: if the
    deliberation raises (an unrecoverable backend/graph failure) or yields no key judgments
    (every role hiccuped), return a labelled digest rather than crashing or emitting an
    empty brief — a /brief request must always get *something* cited back."""
    try:
        state = run_deliberation(query, evidence, backend)
        result = _assemble(query, evidence, state, backend.name)
    except Exception as exc:
        log.warning("deliberation_failed_using_digest", error=str(exc))
        return extractive_brief(query, evidence)
    if not result.key_judgments:
        log.warning("deliberation_empty_using_digest", backend=backend.name)
        return extractive_brief(query, evidence)

    settings = get_settings()
    if settings.assurance_samples > 1:  # self-consistency: calibrate confidence by agreement
        from argus.agent.assurance import assured_confidence

        assured = assured_confidence(
            state, backend, settings.assurance_samples, settings.assurance_temperature
        )
        if assured is None:  # every resample failed — keep the primary panel's confidence
            log.warning("assurance_unavailable_keeping_primary", confidence=result.confidence)
        else:
            result.confidence, result.confidence_agreement = assured
            log.info(
                "assured_confidence",
                confidence=result.confidence,
                agreement=result.confidence_agreement,
            )
    return result


def generate_brief(
    query: str,
    *,
    session: Session | None = None,
    evidence: list[EvidenceItem] | None = None,
    backend: LLMBackend | object | None = _AUTO,
    persist: bool = True,
    mode: str | None = None,
) -> BriefResult:
    """Produce a cited brief. `backend=_AUTO` resolves from settings (free by default);
    pass an explicit backend (or None to force the deterministic digest). `mode` overrides
    `ARGUS_BRIEF_MODE` per call: "quick" = one LLM call (chat-speed, ~30s), "panel" = the
    full multi-agent deliberation (minutes; the deep-analysis path)."""
    # Triage 1: meta/conversational questions get an instant canned answer — a deliberation
    # about "what can you do" is minutes of inference for a predetermined non-answer.
    if is_meta_query(query):
        result = capabilities_brief(query)
        result.evidence = []
        log.info("brief_triaged", kind="meta")
        return result

    settings = get_settings()
    auto_collected: int | None = None
    lanes_consulted: list[str] = []
    lane_reason: str | None = None
    lane_counts: dict[str, int] = {}
    if evidence is None:
        if session is None:
            raise ValueError("generate_brief needs either `evidence` or a `session`")

        def _retrieve() -> list[EvidenceItem]:
            nonlocal lane_counts, lane_reason, lanes_consulted
            # Lean multi-agent fusion: the deterministic supervisor dispatches only the
            # relevant OSINT / Sky / Ocean / Cyber workers. They gather rated EvidenceItems;
            # the existing quick/panel path remains the one central synthesis brain.
            gathered = gather_fused_evidence(
                session,
                query,
                settings.brief_context_docs,
                gather_evidence,
                settings,
            )
            lanes_consulted = list(gathered.lanes_consulted)
            lane_reason = gathered.reason
            lane_counts = {str(lane): count for lane, count in gathered.lane_counts.items()}
            log.info(
                "fusion_routed",
                lanes=lanes_consulted,
                reason=lane_reason,
                counts=gathered.lane_counts,
            )
            return gathered.evidence

        evidence = _retrieve()
        # Collect-on-demand: thin/no relevant coverage -> fetch reporting for the question
        # inline (the corpus is a cache, not a prerequisite), then retrieve again.
        if (
            settings.auto_collect
            and "osint" in lanes_consulted
            and lane_counts.get("osint", 0) < settings.auto_collect_min_relevant
        ):
            _, auto_collected = collect_for_query(session, query)
            if auto_collected:
                evidence = _retrieve()
        # Triage (retrieval path only — explicit `evidence` callers know what they passed):
        # if the corpus still holds nothing relevant after collection, say so instantly
        # instead of deliberating to a predetermined "no evidence".
        if not evidence or _fused_relevant_count(query, evidence) == 0:
            n_docs = session.scalar(select(func.count()).select_from(Document)) or 0
            result = no_reporting_brief(query, n_docs, collection_enabled=settings.auto_collect)
            result.evidence = []
            result.auto_collected = auto_collected
            result.lanes_consulted = lanes_consulted
            result.lane_reason = lane_reason
            log.info("brief_triaged", kind="no_relevant_reporting", corpus_docs=n_docs)
            return result

    # Explicit-evidence callers bypass the worker orchestrator, so enforce the same invariant
    # at the synthesis boundary as well. Duplicate evidence must never receive extra citation
    # weight merely because it arrived through a different entry point.
    evidence = deduplicate_evidence(evidence)

    mode = mode or settings.brief_mode
    mode_reason: str | None = None
    if mode == "auto":
        # Adaptive effort routing: escalate to the panel only where it earns its minutes
        # (attribution questions, low-reliability-only sourcing, contested framing).
        routed, mode_reason = decide_mode(query, evidence, settings.contested_threshold)
        mode = "panel" if routed == "panel" else "quick"
        log.info("brief_routed", mode=mode, reason=mode_reason)
    if backend is _AUTO and mode == "dspy":
        # Optimized single-shot path. Lazy import: the `optimize` extra (DSPy) must not be
        # a hard dependency of the core serving flow.
        from argus.optimize.serve import optimized_brief

        result = optimized_brief(query, evidence)
    else:
        resolved = resolve_backend() if backend is _AUTO else cast(LLMBackend | None, backend)
        if resolved is None:
            result = extractive_brief(query, evidence)
        elif mode in ("student", "quick"):
            # One LLM call instead of the panel: "student" is the distilled model's intended
            # use; "quick" is the chat-speed path (same single-shot prompt, any backend).
            try:
                result = oneshot_brief(query, evidence, resolved)
            except Exception as exc:  # backend hiccup -> labelled digest, never a 500
                log.warning("oneshot_failed_using_digest", error=str(exc))
                result = extractive_brief(query, evidence)
        else:
            result = _deliberate_or_digest(query, evidence, resolved)
    result.evidence = evidence
    result.mode = mode
    result.mode_reason = mode_reason
    result.auto_collected = auto_collected
    result.lanes_consulted = lanes_consulted
    result.lane_reason = lane_reason

    # Reliability-gated calibration: enforce in code the confidence the sourcing warrants,
    # rather than trust the model not to over-read a lone low-reliability source.
    capped, note = apply_confidence_cap(result.confidence, evidence, result.citations)
    if note:
        log.info("confidence_capped", frm=result.confidence, to=capped, reason=note)
        result.confidence = capped
        result.confidence_note = f"Capped to {capped}: {note}."

    if persist and session is not None:
        session.add(to_brief_row(result))
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
    if result.lanes_consulted:
        lines += [f"LANES: {', '.join(result.lanes_consulted)}"]
        if result.lane_reason:
            lines += [f"  ({result.lane_reason})"]
    if result.confidence_note:
        lines += [f"  ({result.confidence_note})"]
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
