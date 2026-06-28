"""ARGUS read-only knowledge-graph API + the hardened analyst /brief route.

Everything except POST /brief is read-only. /brief runs the (potentially expensive)
multi-agent deliberation, so it carries the rate-limit + concurrency guards from
limits.py. GET /model exposes the active inference backend so the model layer is
observable, not hidden, in a deployment.
"""

from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus import __version__
from argus.agent.analyst import generate_brief
from argus.agent.llm import ollama_models, resolve_backend
from argus.api.limits import ConcurrencyLimiter, RateLimiter, SlotUnavailable
from argus.config import get_settings
from argus.db.base import get_session_factory
from argus.db.models import Brief, Document, Event, Narrative, Source

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


class NarrativeOut(BaseModel):
    narrative_id: str
    label: str
    doc_count: int
    source_count: int
    coordination: float | None  # human-review signal in [0,1], not a verdict
    first_seen: str | None
    last_seen: str | None


class BriefOut(BaseModel):
    brief_id: int
    query: str
    confidence: str | None
    backend: str | None
    key_judgments: list[str]
    citations: list[str]
    body: str
    created_at: str | None


class BriefRequest(BaseModel):
    query: str = Field(min_length=1)


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
    rows = db.scalars(select(Document).order_by(Document.published.desc()).limit(limit)).all()
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


@app.get("/events", response_model=list[EventOut])
def events(limit: int = 50, db: Session = Depends(get_db)) -> list[EventOut]:
    limit = max(1, min(limit, 200))
    rows = db.scalars(
        select(Event).order_by(Event.source_count.desc(), Event.doc_count.desc()).limit(limit)
    ).all()
    return [
        EventOut(
            event_id=e.event_id,
            title=e.title,
            occurred=e.occurred.isoformat() if e.occurred else None,
            doc_count=e.doc_count,
            source_count=e.source_count,
        )
        for e in rows
    ]


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
            first_seen=n.first_seen.isoformat() if n.first_seen else None,
            last_seen=n.last_seen.isoformat() if n.last_seen else None,
        )
        for n in rows
    ]


def _brief_out(b: Brief) -> BriefOut:
    return BriefOut(
        brief_id=b.brief_id,
        query=b.query,
        confidence=b.confidence,
        backend=b.backend,
        key_judgments=b.key_judgments or [],
        citations=b.citations or [],
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
            result = generate_brief(payload.query, session=db, persist=False)
    except SlotUnavailable as exc:
        raise HTTPException(status_code=503, detail="server busy, try again shortly") from exc

    row = Brief(
        query=result.query,
        body=result.body,
        confidence=result.confidence,
        backend=result.backend,
        key_judgments=result.key_judgments or None,
        citations=result.citations or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _brief_out(row)
