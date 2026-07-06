"""ARGUS read-only knowledge-graph API + the hardened analyst /brief route.

Everything except POST /brief is read-only. /brief runs the (potentially expensive)
multi-agent deliberation, so it carries the rate-limit + concurrency guards from
limits.py. GET /model exposes the active inference backend so the model layer is
observable, not hidden, in a deployment.
"""

from collections.abc import Iterator
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus import __version__
from argus.actors import THREAT_ACTORS
from argus.agent.analyst import gather_evidence, generate_brief, to_brief_row
from argus.agent.llm import ollama_models, resolve_backend
from argus.agent.state import EvidenceItem
from argus.api.limits import ConcurrencyLimiter, RateLimiter, SlotUnavailable
from argus.config import get_settings
from argus.db.base import get_session_factory
from argus.db.models import Brief, Document, Event, Narrative, Source
from argus.nlp.disarm import DISARM_TECHNIQUES, default_mapper, lexical_match
from argus.stix import to_stix_bundle

settings = get_settings()
app = FastAPI(title="ARGUS", version=__version__, description="All-source intelligence workbench")

_allowed = [o.strip() for o in settings.api_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed or [],
    allow_origin_regex=None if _allowed else r"http://localhost:\d+",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_rate_limiter = RateLimiter(
    settings.api_rate_limit_requests,
    settings.api_rate_limit_window_seconds,
    settings.api_trust_forwarded_header,
)
_concurrency = ConcurrencyLimiter(
    settings.api_inference_concurrency,
    settings.api_inference_acquire_timeout_seconds,
)


def get_db() -> Iterator[Session]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


# --- response models -----------------------------------------------------------------
class Health(BaseModel):
    status: str = "ok"
    version: str


class ModelInfo(BaseModel):
    configured: str  # ARGUS_LLM_BACKEND
    active: str  # the backend that would actually run a brief
    ollama_models: list[str]


class Stats(BaseModel):
    documents: int
    sources: int
    events: int
    narratives: int
    briefs: int


class SourceOut(BaseModel):
    label: str
    name: str | None
    kind: str | None
    reliability: str


class DocumentOut(BaseModel):
    doc_id: str
    source: str
    title: str
    summary: str | None
    url: str | None
    published: str | None
    credibility: int | None


class EventOut(BaseModel):
    event_id: str
    title: str
    occurred: str | None
    doc_count: int
    source_count: int
    divergence: float | None = None  # framing divergence [0,1] — contested-event signal


class DisarmTag(BaseModel):
    technique_id: str  # DISARM Red Framework id, e.g. "T0086.002"
    name: str
    phase: str  # Plan | Prepare | Execute | Assess
    score: float


class DisarmTechniqueOut(BaseModel):
    technique_id: str
    name: str
    phase: str
    description: str


class ThreatActorOut(BaseModel):
    name: str
    nation: str  # open-reporting attribution consensus — contested, human-review
    aliases: list[str]
    note: str


class NarrativeOut(BaseModel):
    narrative_id: str
    label: str
    doc_count: int
    source_count: int
    coordination: float | None  # human-review signal in [0,1], not a verdict
    # DISARM influence-ops techniques the framing resembles — advisory, human-review, symmetric
    # to SENTINEL's ATT&CK tags. Empty for narratives tagged before DISARM landed.
    disarm: list[DisarmTag] = []
    first_seen: str | None
    last_seen: str | None


class EvidenceOut(BaseModel):
    doc_id: str
    title: str
    source: str
    reliability: str  # Admiralty source reliability A-F
    credibility: int | None  # Admiralty information credibility 1-6
    rating: str  # compact Admiralty code, e.g. "B2"
    summary: str | None
    published: str | None
    url: str | None


class AchScoreOut(BaseModel):
    hypothesis: str
    inconsistency: float  # reliability-weighted disconfirming evidence (lower = stronger)
    consistent: int
    inconsistent: int


class BriefOut(BaseModel):
    brief_id: int
    query: str
    confidence: str | None
    backend: str | None
    key_judgments: list[str]
    citations: list[str]
    # Structured Analytic Technique sections — the full intelligence product.
    key_assumptions: list[str] = []
    indicators: list[str] = []
    hypotheses: list[str] = []
    ach_ranking: list[AchScoreOut] = []
    alternatives: str | None = None
    gaps: str | None = None
    critique_response: str | None = None
    # The cited evidence items with their Admiralty ratings (incl. cyber-fusion items),
    # in citation order. Populated on a fresh POST /brief; [] for persisted listings.
    evidence: list[EvidenceOut] = []
    # Adaptive-path transparency (fresh POST /brief only): which mode actually ran, why the
    # router chose it, and how many documents collect-on-demand fetched for this question.
    mode: str | None = None
    mode_reason: str | None = None
    auto_collected: int | None = None
    body: str
    created_at: str | None


class BriefRequest(BaseModel):
    query: str = Field(min_length=1)
    # "auto" = the effort router decides (default); "quick" = one LLM call (chat-speed);
    # "deliberate" = the full multi-agent ACH panel.
    mode: Literal["auto", "deliberate", "quick"] = "auto"


class IngestRequest(BaseModel):
    query: str = Field(min_length=2)


class IngestResult(BaseModel):
    fetched: int  # articles GDELT returned for the query
    new: int  # documents actually added (existing ones are never clobbered)
    documents: int  # corpus size after ingest + enrich


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=8, ge=1, le=50)


class MapDisarmRequest(BaseModel):
    text: str = Field(min_length=1)


# --- read-only routes ----------------------------------------------------------------
@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(version=__version__)


@app.get("/model", response_model=ModelInfo)
def model_info() -> ModelInfo:
    backend = resolve_backend()
    return ModelInfo(
        configured=settings.llm_backend,
        active=backend.name if backend else "template",
        ollama_models=ollama_models(settings.ollama_url),
    )


@app.get("/stats", response_model=Stats)
def stats(db: Session = Depends(get_db)) -> Stats:
    def count(model: type) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    return Stats(
        documents=count(Document),
        sources=count(Source),
        events=count(Event),
        narratives=count(Narrative),
        briefs=count(Brief),
    )


@app.get("/sources", response_model=list[SourceOut])
def sources(db: Session = Depends(get_db)) -> list[SourceOut]:
    rows = db.scalars(select(Source).order_by(Source.reliability, Source.label)).all()
    return [
        SourceOut(label=s.label, name=s.name, kind=s.kind, reliability=s.reliability) for s in rows
    ]


@app.get("/documents", response_model=list[DocumentOut])
def documents(limit: int = 50, db: Session = Depends(get_db)) -> list[DocumentOut]:
    limit = max(1, min(limit, 200))
    # nulls_last: Postgres puts NULLs first under DESC, which would lead with undated docs.
    rows = db.scalars(
        select(Document).order_by(Document.published.desc().nulls_last()).limit(limit)
    ).all()
    return [
        DocumentOut(
            doc_id=d.doc_id,
            source=d.source,
            title=d.title,
            summary=d.summary,
            url=d.url,
            published=d.published.isoformat() if d.published else None,
            credibility=d.credibility,
        )
        for d in rows
    ]


def _event_out(e: Event) -> EventOut:
    return EventOut(
        event_id=e.event_id,
        title=e.title,
        occurred=e.occurred.isoformat() if e.occurred else None,
        doc_count=e.doc_count,
        source_count=e.source_count,
        divergence=e.divergence,
    )


@app.get("/events", response_model=list[EventOut])
def events(limit: int = 50, db: Session = Depends(get_db)) -> list[EventOut]:
    limit = max(1, min(limit, 200))
    rows = db.scalars(
        select(Event).order_by(Event.source_count.desc(), Event.doc_count.desc()).limit(limit)
    ).all()
    return [_event_out(e) for e in rows]


@app.get("/contested", response_model=list[EventOut])
def contested(limit: int = 50, db: Session = Depends(get_db)) -> list[EventOut]:
    """Events whose sources DISAGREE in framing (divergence >= threshold), most-contested
    first — the inverse of narrative coordination. A human-review signal: contradictions
    are where deception, error, or a developing situation surface."""
    limit = max(1, min(limit, 200))
    rows = db.scalars(
        select(Event)
        .where(
            Event.source_count >= 2,
            Event.divergence >= settings.contested_threshold,
        )
        .order_by(Event.divergence.desc())
        .limit(limit)
    ).all()
    return [_event_out(e) for e in rows]


@app.get("/narratives", response_model=list[NarrativeOut])
def narratives(limit: int = 50, db: Session = Depends(get_db)) -> list[NarrativeOut]:
    """Narrative clusters, most-coordinated first (a human-review signal, not a verdict)."""
    limit = max(1, min(limit, 200))
    rows = db.scalars(select(Narrative).order_by(Narrative.coordination.desc()).limit(limit)).all()
    return [
        NarrativeOut(
            narrative_id=n.narrative_id,
            label=n.label,
            doc_count=n.doc_count,
            source_count=n.source_count,
            coordination=n.coordination,
            disarm=[DisarmTag(**tag) for tag in (n.disarm or [])],
            first_seen=n.first_seen.isoformat() if n.first_seen else None,
            last_seen=n.last_seen.isoformat() if n.last_seen else None,
        )
        for n in rows
    ]


@app.get("/disarm/techniques", response_model=list[DisarmTechniqueOut])
def disarm_catalog() -> list[DisarmTechniqueOut]:
    """The DISARM influence-ops technique catalog ARGUS tags narratives against — the twin of
    SENTINEL's ATT&CK `/techniques`. Reference data (no model), so cyber TTPs and influence
    TTPs share one shape for a hybrid-threat picture."""
    return [
        DisarmTechniqueOut(
            technique_id=t.technique_id, name=t.name, phase=t.phase, description=t.description
        )
        for t in DISARM_TECHNIQUES
    ]


@app.get("/actors", response_model=list[ThreatActorOut])
def actors() -> list[ThreatActorOut]:
    """The threat-actor → nation attribution registry — the cross-graph join that links a cyber
    campaign (or an OSINT mention) to the geopolitical actor a brief is about. Attribution is the
    consensus of open reporting, contested and human-review, never an automated verdict."""
    return [
        ThreatActorOut(name=a.name, nation=a.nation, aliases=list(a.aliases), note=a.note)
        for a in THREAT_ACTORS
    ]


@app.get("/stix")
def stix_export(db: Session = Depends(get_db)) -> dict[str, object]:
    """STIX 2.1 bundle of the influence-ops graph — DISARM techniques (attack-pattern), tagged
    narratives (report), and sources (identity). Ingestible by OpenCTI / MISP / the ATT&CK
    Navigator, and joinable with SENTINEL's ATT&CK STIX in one object model. Read-only."""
    return to_stix_bundle(db)


@app.post("/map-disarm", response_model=list[DisarmTag])
def map_disarm(payload: MapDisarmRequest, request: Request) -> list[DisarmTag]:
    """Zero-shot DISARM tagging of pasted text — the symmetric twin of SENTINEL's
    POST /map-techniques (ATT&CK). Inspects the supplied text only, never fetches a URL, so the
    graph stays read-only. Advisory human-review signal; degrades to lexical matching when
    embeddings are unavailable (never 500s)."""
    if len(payload.text) > settings.api_max_request_chars:
        raise HTTPException(status_code=422, detail="text too long")
    if not _rate_limiter.allow(request):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    try:
        matches = default_mapper().map_text(
            payload.text, top_k=settings.disarm_top_k, threshold=settings.disarm_threshold
        )
    except Exception:  # model unavailable/slim image -> dependency-free lexical fallback
        matches = lexical_match(payload.text, top_k=settings.disarm_top_k)
    return [
        DisarmTag(technique_id=m.technique_id, name=m.name, phase=m.phase, score=round(m.score, 3))
        for m in matches
    ]


def _evidence_out(e: EvidenceItem) -> EvidenceOut:
    return EvidenceOut(
        doc_id=e.doc_id,
        title=e.title,
        source=e.source,
        reliability=e.reliability,
        credibility=e.credibility,
        rating=e.rating(),
        summary=e.summary,
        published=e.published,
        url=e.url,
    )


def _brief_out(b: Brief, evidence: list[EvidenceOut] | None = None) -> BriefOut:
    return BriefOut(
        brief_id=b.brief_id,
        query=b.query,
        confidence=b.confidence,
        backend=b.backend,
        key_judgments=b.key_judgments or [],
        citations=b.citations or [],
        key_assumptions=b.key_assumptions or [],
        indicators=b.indicators or [],
        hypotheses=b.hypotheses or [],
        ach_ranking=[AchScoreOut(**row) for row in (b.ach_ranking or [])],
        alternatives=b.alternatives,
        gaps=b.gaps,
        critique_response=b.critique_response,
        evidence=evidence or [],
        body=b.body,
        created_at=b.created_at.isoformat() if b.created_at else None,
    )


@app.get("/briefs", response_model=list[BriefOut])
def briefs(limit: int = 20, db: Session = Depends(get_db)) -> list[BriefOut]:
    limit = max(1, min(limit, 100))
    rows = db.scalars(select(Brief).order_by(Brief.created_at.desc()).limit(limit)).all()
    return [_brief_out(b) for b in rows]


@app.get("/briefs/{brief_id}", response_model=BriefOut)
def brief_detail(brief_id: int, db: Session = Depends(get_db)) -> BriefOut:
    row = db.get(Brief, brief_id)
    if row is None:
        raise HTTPException(status_code=404, detail="brief not found")
    return _brief_out(row)


# --- read-only OSINT retrieval (the reverse-direction fusion hook) -------------------
@app.post("/retrieve", response_model=list[EvidenceOut])
def retrieve(
    payload: RetrieveRequest, request: Request, db: Session = Depends(get_db)
) -> list[EvidenceOut]:
    """Hybrid OSINT retrieval — rated evidence for a query, no LLM. Lets a sibling platform
    (e.g. SENTINEL) pull the open-source picture relevant to its own analysis. Read-only and
    cheap (rate-limited, but no inference-concurrency cap)."""
    if len(payload.query) > settings.api_max_request_chars:
        raise HTTPException(status_code=422, detail="query too long")
    if not _rate_limiter.allow(request):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    return [_evidence_out(e) for e in gather_evidence(db, payload.query, payload.k)]


# --- collection from the dashboard (guarded write) -----------------------------------
@app.post("/ingest", response_model=IngestResult)
def ingest(payload: IngestRequest, request: Request, db: Session = Depends(get_db)) -> IngestResult:
    """Ingest open-source reporting on a topic (GDELT DOC 2.0) + enrich, from the dashboard —
    so the Collection view can fill the corpus without the CLI. Guarded like /brief (rate
    limit + bounded concurrency): it fetches externally and runs the embedding model."""
    if len(payload.query) > settings.api_max_request_chars:
        raise HTTPException(status_code=422, detail="query too long")
    if not _rate_limiter.allow(request):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    from argus.collection.ondemand import collect_for_query

    try:
        with _concurrency.slot():
            fetched, new = collect_for_query(db, payload.query)  # best-effort; (0,0) upstream-fail
            db.commit()
    except SlotUnavailable as exc:
        raise HTTPException(status_code=503, detail="server busy, try again shortly") from exc
    except Exception as exc:  # persistence failure -> a clear 502, not a stack trace
        db.rollback()
        raise HTTPException(status_code=502, detail=f"ingest failed: {exc}") from exc
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    return IngestResult(fetched=fetched, new=new, documents=total)


# --- the expensive agent route (guarded) ---------------------------------------------
@app.post("/brief", response_model=BriefOut)
def create_brief(
    payload: BriefRequest, request: Request, db: Session = Depends(get_db)
) -> BriefOut:
    if len(payload.query) > settings.api_max_request_chars:
        raise HTTPException(status_code=422, detail="query too long")
    if not _rate_limiter.allow(request):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    try:
        with _concurrency.slot():
            mode = {"quick": "quick", "deliberate": "panel", "auto": "auto"}[payload.mode]
            result = generate_brief(payload.query, session=db, persist=False, mode=mode)
    except SlotUnavailable as exc:
        raise HTTPException(status_code=503, detail="server busy, try again shortly") from exc

    row = to_brief_row(result)
    if result.backend == "triage":
        # Instant guidance (meta question / no relevant reporting) — returned to the chat
        # but never persisted: /briefs lists intelligence products, not help text.
        row.brief_id = 0
        out = _brief_out(row, [])
        out.auto_collected = result.auto_collected  # "collected N, still nothing relevant"
        return out
    db.add(row)
    db.commit()
    db.refresh(row)
    # Return the cited evidence items (in citation order) so the dashboard can render
    # rated evidence cards — including cyber-fusion items, which have no Document row.
    by_id = {e.doc_id: e for e in result.evidence}
    cited = [_evidence_out(by_id[c]) for c in result.citations if c in by_id]
    out = _brief_out(row, cited)
    out.mode, out.mode_reason, out.auto_collected = (
        result.mode,
        result.mode_reason,
        result.auto_collected,
    )
    return out
