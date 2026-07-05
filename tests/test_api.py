from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from argus.api import app as app_module
from argus.api.app import app, get_db
from argus.api.limits import ConcurrencyLimiter, RateLimiter
from argus.db import models  # noqa: F401
from argus.db.base import Base
from argus.db.models import Document, Source


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as seed:
        seed.add(Source(label="reuters.com", name="Reuters", kind="wire", reliability="B"))
        seed.add(
            Document(
                doc_id="reuters.com:1",
                source="reuters.com",
                title="Standoff at the disputed reef",
                summary="Coast guard vessels confronted boats at the reef.",
                credibility=3,
            )
        )
        seed.commit()

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    # Force the deterministic template backend (no Ollama/network in tests).
    monkeypatch.setattr("argus.agent.analyst.resolve_backend", lambda: None)
    monkeypatch.setattr("argus.api.app.resolve_backend", lambda: None)
    monkeypatch.setattr("argus.api.app.ollama_models", lambda url: [])
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_actors_registry(client: TestClient) -> None:
    r = client.get("/actors")
    assert r.status_code == 200
    apt28 = next(a for a in r.json() if a["name"] == "APT28")
    assert apt28["nation"] == "Russia" and "Fancy Bear" in apt28["aliases"]


def test_stix_export(client: TestClient) -> None:
    r = client.get("/stix")
    assert r.status_code == 200
    bundle = r.json()
    assert bundle["type"] == "bundle"
    # DISARM catalog is always exported as attack-patterns (even with no narratives seeded).
    assert any(
        o["type"] == "attack-pattern" and o["external_references"][0]["source_name"] == "DISARM"
        for o in bundle["objects"]
    )


def test_disarm_catalog(client: TestClient) -> None:
    r = client.get("/disarm/techniques")
    assert r.status_code == 200
    rows = r.json()
    assert "T0086.002" in {t["technique_id"] for t in rows}  # the deepfake technique
    assert all(t["phase"] in {"Plan", "Prepare", "Execute", "Assess"} for t in rows)


def test_map_disarm_degrades_to_lexical(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the embedding path to fail -> the endpoint must fall back to lexical, never 500
    # (and never trigger a real model download in CI).
    def boom() -> object:
        raise RuntimeError("no model")

    monkeypatch.setattr("argus.api.app.default_mapper", boom)
    r = client.post(
        "/map-disarm", json={"text": "state outlet floods the space with conspiracy narratives"}
    )
    assert r.status_code == 200
    tags = r.json()
    assert isinstance(tags, list) and tags  # lexical fallback still returns advisory tags
    assert all({"technique_id", "name", "phase", "score"} <= set(t) for t in tags)


def test_model_info_exposes_active_backend(client: TestClient) -> None:
    body = client.get("/model").json()
    assert body["active"] == "template"  # forced in the fixture
    assert "configured" in body and "ollama_models" in body


def test_stats_and_sources(client: TestClient) -> None:
    stats = client.get("/stats").json()
    assert stats["documents"] == 1 and stats["sources"] == 1
    sources = client.get("/sources").json()
    assert sources[0]["reliability"] == "B"


def test_brief_roundtrip_persists(client: TestClient) -> None:
    r = client.post("/brief", json={"query": "standoff at the disputed reef"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "template"
    assert "reuters.com:1" in body["citations"]
    # the cited evidence rides along, rated, so the dashboard can render evidence cards
    assert [e["doc_id"] for e in body["evidence"]] == body["citations"]
    assert body["evidence"][0]["rating"] == "B3"
    # it was persisted and is now listable (persisted listings carry no evidence items)
    listed = client.get("/briefs").json()
    assert len(listed) == 1
    assert listed[0]["evidence"] == []
    detail = client.get(f"/briefs/{listed[0]['brief_id']}")
    assert detail.status_code == 200
    # tradecraft sections round-trip through persistence (template digest sets gaps;
    # the deliberated path fills assumptions/indicators/ach_ranking too).
    stored = detail.json()
    assert stored["gaps"] and "deterministic fallback" in stored["gaps"]
    assert stored["key_assumptions"] == [] and stored["ach_ranking"] == []


def test_brief_rejects_oversized_query(client: TestClient) -> None:
    r = client.post("/brief", json={"query": "x" * 5000})
    assert r.status_code == 422


def test_retrieve_returns_rated_osint(client: TestClient) -> None:
    # The reverse-fusion hook: hybrid retrieval -> rated evidence, no LLM.
    r = client.post("/retrieve", json={"query": "standoff at the disputed reef", "k": 3})
    assert r.status_code == 200
    items = r.json()
    assert items and items[0]["doc_id"] == "reuters.com:1"
    assert items[0]["reliability"] == "B" and items[0]["rating"] == "B3"
    assert "title" in items[0] and "source" in items[0]


def test_brief_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_rate_limiter", RateLimiter(1, 60.0, False))
    assert client.post("/brief", json={"query": "first"}).status_code == 200
    assert client.post("/brief", json={"query": "second"}).status_code == 429


def test_brief_returns_503_when_saturated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Occupy the only inference slot so the request can't acquire one in time -> 503,
    # not a crash or an unbounded queue (the concurrency guard from limits.py).
    limiter = ConcurrencyLimiter(limit=1, acquire_timeout=0.05)
    assert limiter._sem.acquire() is True
    monkeypatch.setattr(app_module, "_concurrency", limiter)
    assert client.post("/brief", json={"query": "while busy"}).status_code == 503


def test_unknown_brief_404(client: TestClient) -> None:
    assert client.get("/briefs/999").status_code == 404
