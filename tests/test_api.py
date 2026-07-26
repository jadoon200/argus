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
from argus.db.models import Brief, Document, Source


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

    # Force the deterministic template backend (no Ollama/network in tests), and make
    # collect-on-demand find nothing rather than call GDELT.
    monkeypatch.setattr("argus.agent.analyst.resolve_backend", lambda: None)
    monkeypatch.setattr("argus.api.app.resolve_backend", lambda: None)
    monkeypatch.setattr("argus.api.app.ollama_models", lambda url: [])
    monkeypatch.setattr("argus.agent.analyst.collect_for_query", lambda s, q: (0, 0))
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auto_mode_routes_and_reports(client: TestClient) -> None:
    # Default mode is auto: the router decides and the response says what ran and why.
    r = client.post("/brief", json={"query": "standoff at the disputed reef"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "quick"  # descriptive question -> single pass
    assert body["mode_reason"] and "single pass" in body["mode_reason"]
    assert body["lanes_consulted"] == ["osint", "ocean"]
    assert body["lane_reason"] and "ocean matched" in body["lane_reason"]


def test_auto_mode_escalates_attribution_questions(client: TestClient) -> None:
    r = client.post("/brief", json={"query": "Who is behind the standoff at the reef?"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "panel"  # attribution -> the deliberation path
    assert body["mode_reason"] and "attribution" in body["mode_reason"]


def test_quick_mode_brief(client: TestClient) -> None:
    # mode=quick routes to the single-call path; with no backend it degrades to the digest.
    r = client.post("/brief", json={"query": "standoff at the disputed reef", "mode": "quick"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "template"  # resolved backend is None in tests -> digest
    assert body["citations"] == ["reuters.com:1"]


def test_ingest_endpoint_guarded_and_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GDELT is mocked out; zero new docs must not trigger enrichment (no model in CI).
    # NB: patch the name where ondemand.py bound it, not the defining module.
    monkeypatch.setattr("argus.collection.ondemand.fetch_gdelt_articles", lambda q: [])
    r = client.post("/ingest", json={"query": "South China Sea"})
    assert r.status_code == 200
    body = r.json()
    assert body["fetched"] == 0 and body["new"] == 0
    assert body["documents"] == 1  # the seeded corpus is intact


def test_meta_question_answers_instantly_and_is_not_persisted(client: TestClient) -> None:
    r = client.post("/brief", json={"query": "what can u do"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "triage" and body["brief_id"] == 0
    assert "ARGUS" in body["body"]
    # Guidance is never persisted into the intelligence-product listing.
    assert all(b["backend"] != "triage" for b in client.get("/briefs").json())


def test_irrelevant_query_gets_collection_guidance(client: TestClient) -> None:
    r = client.post("/brief", json={"query": "quantum banking collapse in the metaverse"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "triage"
    assert "collect" in body["body"].lower() and "make ingest" in body["body"]


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


def test_fusion_overview_exposes_all_four_lanes(client: TestClient) -> None:
    rows = client.get("/overview").json()
    assert [row["lane"] for row in rows] == ["osint", "sky", "ocean", "cyber"]
    osint = rows[0]
    assert osint["status"] == "ready" and osint["count"] == 1
    assert osint["last_item"]["doc_id"] == "reuters.com:1"
    # The test settings deliberately leave sibling URLs empty: visible disabled state,
    # not a false green light or a failed endpoint.
    assert all(row["status"] == "disabled" for row in rows[1:])


def test_fusion_preview_routes_and_gathers_without_an_llm(client: TestClient) -> None:
    r = client.post(
        "/fusion/preview", json={"query": "Assess vessels near the disputed reef", "k": 3}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lanes_consulted"] == ["osint", "ocean"]
    assert body["lane_counts"] == {"osint": 1, "ocean": 0}
    assert [item["doc_id"] for item in body["evidence"]] == ["reuters.com:1"]


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


def _seed_snapshot_brief(client: TestClient, query: str) -> None:
    """Insert a model-produced brief the way `seed_demo.py` bakes snapshots in."""
    db = next(app.dependency_overrides[get_db]())
    db.add(
        Brief(
            query=query,
            body="KEY JUDGMENTS: ...",
            key_judgments=["Vessels massed at the reef [E1]"],
            citations=["reuters.com:1"],
            confidence="moderate",
            backend="ollama:qwen2.5:14b",
        )
    )
    db.commit()


def test_briefs_query_lookup_serves_snapshot_with_evidence(client: TestClient) -> None:
    """The snapshot path for the model-less demo deploy: an exact-question lookup on
    /briefs returns the persisted brief WITH cited evidence hydrated, so the dashboard
    can render the full product without running a model."""
    _seed_snapshot_brief(client, "standoff at the disputed reef")
    # Case/whitespace-insensitive match; hydrated evidence mirrors the citations.
    hits = client.get("/briefs", params={"q": "  Standoff at the DISPUTED reef "}).json()
    assert len(hits) == 1
    assert [e["doc_id"] for e in hits[0]["evidence"]] == hits[0]["citations"]
    assert hits[0]["evidence"][0]["rating"] == "B3"
    # No match -> empty list (the frontend falls through to the live route).
    assert client.get("/briefs", params={"q": "unrelated question"}).json() == []


def test_briefs_query_lookup_never_serves_a_template_digest_as_a_snapshot(
    client: TestClient,
) -> None:
    """POST /brief persists whatever it produced, so on the template-backed demo deploy a
    visitor's own free-typed question becomes a stored template digest. The snapshot
    lookup must not hand that back — the dashboard would label a live deterministic digest
    a 'precomputed full-panel brief'. Only real model products are snapshots."""
    q = "standoff at the disputed reef"  # shares corpus tokens, so it really briefs
    posted = client.post("/brief", json={"query": q})
    assert posted.status_code == 200 and posted.json()["backend"] == "template"
    # It is persisted and listable...
    assert any(b["query"].lower() == q for b in client.get("/briefs").json())
    # ...but invisible to the snapshot lookup, so the UI falls through to the live route.
    assert client.get("/briefs", params={"q": q}).json() == []


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
