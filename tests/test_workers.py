from collections.abc import Callable

import httpx
import pytest
import respx
from sqlalchemy.orm import Session

from argus.agent.analyst import generate_brief
from argus.agent.state import EvidenceItem
from argus.agent.workers import (
    OsintWorker,
    SkyWorker,
    gather_fused_evidence,
    overview_statuses,
)
from argus.config import Settings
from argus.db.models import Document, Source


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, auto_collect=False, **kw)  # type: ignore[arg-type]


def _item(doc_id: str, source: str, title: str) -> EvidenceItem:
    return EvidenceItem(
        doc_id=doc_id,
        title=title,
        source=source,
        reliability="B",
        credibility=2,
        summary=title,
    )


def _osint(_session: Session, _query: str, _limit: int) -> list[EvidenceItem]:
    return [_item("news:1", "news", "News reporting")]


def _must_not_run(lane: str) -> Callable[..., list[EvidenceItem]]:
    def fail(*_args: object, **_kwargs: object) -> list[EvidenceItem]:
        raise AssertionError(f"{lane} worker should not have been dispatched")

    return fail


def test_ocean_plan_dispatches_ocean_not_sky_or_cyber(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "argus.agent.workers.ocean_evidence",
        lambda *_args, **_kwargs: [_item("ocean-geoint:1", "ocean-geoint", "AIS vessel gap")],
    )
    monkeypatch.setattr("argus.agent.workers.sky_evidence", _must_not_run("sky"))
    monkeypatch.setattr("argus.agent.workers.cyber_evidence", _must_not_run("cyber"))

    gathered = gather_fused_evidence(
        session,
        "Suspicious vessel activity in the Singapore Strait",
        8,
        _osint,
        _settings(),
    )
    assert gathered.lanes_consulted == ["osint", "ocean"]
    assert [item.doc_id for item in gathered.evidence] == ["news:1", "ocean-geoint:1"]
    assert gathered.lane_counts == {"osint": 1, "ocean": 1}


def test_cyber_plan_dispatches_cyber_only(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "argus.agent.workers.cyber_evidence",
        lambda *_args, **_kwargs: [
            _item("sentinel-cyber:1", "sentinel-cyber", "Ransomware campaign")
        ],
    )
    monkeypatch.setattr("argus.agent.workers.sky_evidence", _must_not_run("sky"))
    monkeypatch.setattr("argus.agent.workers.ocean_evidence", _must_not_run("ocean"))

    gathered = gather_fused_evidence(
        session, "Ransomware exploitation campaign", 8, _osint, _settings()
    )
    assert gathered.lanes_consulted == ["osint", "cyber"]
    assert {item.source for item in gathered.evidence} == {"news", "sentinel-cyber"}


def test_routed_lane_falls_back_to_salient_when_the_filter_empties(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A domain-level question routes to a lane but shares no subject token with any specific
    incident, so the per-incident filter matches nothing. The lane must still surface its top
    incidents. Regression for the live `ocean · 0` on "the most major incident in the ocean".
    """

    def ocean(_settings: object, limit: int = 5, query: str | None = None) -> list[EvidenceItem]:
        # With a query the per-incident filter matches nothing; without one, the salient top.
        if query:
            return []
        return [_item("ocean-geoint:top", "ocean-geoint", "AIS spoofing - MMSI 563000029")]

    monkeypatch.setattr("argus.agent.workers.ocean_evidence", ocean)
    monkeypatch.setattr("argus.agent.workers.sky_evidence", _must_not_run("sky"))
    monkeypatch.setattr("argus.agent.workers.cyber_evidence", _must_not_run("cyber"))

    gathered = gather_fused_evidence(
        session,
        "overview of the most major incident in the ocean for pharos",
        8,
        _osint,
        _settings(),
    )
    assert gathered.lanes_consulted == ["osint", "ocean"]
    assert "ocean-geoint:top" in [item.doc_id for item in gathered.evidence]
    assert gathered.lane_counts["ocean"] == 1


def test_supervisor_flag_off_restores_flat_fusion_and_deduplicates(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "argus.agent.workers.sky_evidence",
        lambda *_args, **_kwargs: [_item("shared", "sky-geoint", "Sky")],
    )
    monkeypatch.setattr(
        "argus.agent.workers.ocean_evidence",
        lambda *_args, **_kwargs: [_item("shared", "ocean-geoint", "Ocean")],
    )
    monkeypatch.setattr(
        "argus.agent.workers.cyber_evidence",
        lambda *_args, **_kwargs: [_item("sentinel-cyber:1", "sentinel-cyber", "Cyber")],
    )
    gathered = gather_fused_evidence(
        session,
        "political coalition",
        8,
        _osint,
        _settings(fusion_supervisor=False),
    )
    assert gathered.lanes_consulted == ["osint", "sky", "ocean", "cyber"]
    assert [item.doc_id for item in gathered.evidence] == ["news:1", "shared", "sentinel-cyber:1"]
    assert "legacy flat fusion" in gathered.reason


def test_fusion_round_robins_lanes_so_sibling_evidence_is_not_buried(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def many_osint(_session: Session, _query: str, _limit: int) -> list[EvidenceItem]:
        return [_item(f"news:{i}", "news", f"News {i}") for i in range(3)]

    monkeypatch.setattr(
        "argus.agent.workers.ocean_evidence",
        lambda *_args, **_kwargs: [
            _item(f"ocean-geoint:{i}", "ocean-geoint", f"Ocean {i}") for i in range(2)
        ],
    )
    gathered = gather_fused_evidence(session, "Vessels in the strait", 8, many_osint, _settings())
    assert [item.doc_id for item in gathered.evidence] == [
        "news:0",
        "ocean-geoint:0",
        "news:1",
        "ocean-geoint:1",
        "news:2",
    ]


def test_disabled_worker_degrades_to_empty_and_reports_disabled() -> None:
    worker = SkyWorker(_settings(horus_api_url=""))
    assert worker.gather("GNSS jamming", 5) == []
    status = worker.status()
    assert status.configured is False and status.reachable is False


@respx.mock
def test_configured_sky_worker_reports_health_count_and_last_item() -> None:
    respx.get("http://horus.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://horus.test/stats").mock(
        return_value=httpx.Response(200, json={"incidents": 4})
    )
    respx.get("http://horus.test/geoint/evidence").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "doc_id": "jam-1",
                    "title": "GNSS interference near an air corridor",
                    "reliability": "C",
                    "credibility": 2,
                    "url": "/incidents/jam-1",
                }
            ],
        )
    )
    status = SkyWorker(_settings(horus_api_url="http://horus.test")).status()
    assert status.configured is True and status.reachable is True
    assert status.count == 4 and status.count_label == "incidents"
    assert status.last_item is not None
    assert status.last_item.doc_id == "sky-geoint:jam-1"
    assert status.last_item.url == "http://horus.test/incidents/jam-1"


def test_osint_status_and_overview_preserve_lane_order(session: Session) -> None:
    session.add(Source(label="reuters.com", reliability="B"))
    session.add(
        Document(
            doc_id="reuters.com:1",
            source="reuters.com",
            title="Latest open-source report",
            summary="A source-rated report for the fusion overview.",
        )
    )
    session.flush()
    osint = OsintWorker(session, _osint).status()
    assert osint.count == 1 and osint.last_item is not None
    assert osint.last_item.title == "Latest open-source report"

    statuses = overview_statuses(session, _osint, _settings())
    assert [status.lane for status in statuses] == ["osint", "sky", "ocean", "cyber"]
    assert statuses[0].reachable is True
    assert all(not status.configured for status in statuses[1:])


def test_generate_brief_surfaces_selected_workers(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The integration boundary under test is supervisor → workers → brief metadata; never
    # let the default collect-on-demand path turn this into a live GDELT test.
    monkeypatch.setattr("argus.agent.analyst.collect_for_query", lambda _db, _query: (0, 0))
    session.add(Source(label="reuters.com", reliability="B"))
    session.add(
        Document(
            doc_id="reuters.com:reef",
            source="reuters.com",
            title="Vessels approach the disputed reef",
            summary="Coast guard vessels approached the disputed reef in the South China Sea.",
        )
    )
    session.flush()
    monkeypatch.setattr(
        "argus.agent.workers.ocean_evidence",
        lambda *_args, **_kwargs: [
            _item("ocean-geoint:v1", "ocean-geoint", "Vessel rendezvous near the reef")
        ],
    )
    monkeypatch.setattr("argus.agent.workers.sky_evidence", _must_not_run("sky"))
    monkeypatch.setattr("argus.agent.workers.cyber_evidence", _must_not_run("cyber"))

    result = generate_brief(
        "Assess vessels near the disputed reef",
        session=session,
        backend=None,
        persist=False,
    )
    assert result.lanes_consulted == ["osint", "ocean"]
    assert result.lane_reason is not None and "ocean matched" in result.lane_reason
    assert {item.source for item in result.evidence} == {"reuters.com", "ocean-geoint"}
