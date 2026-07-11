import httpx
import respx

from argus.bridge.sentinel import SentinelBridge, cyber_evidence
from argus.config import Settings

# Mirrors SENTINEL's real /campaigns CampaignSummary: `techniques` are OBJECTS (not bare
# strings), with `kev_cves` and `age_days` alongside. The previous fixture used string
# techniques and no KEV — a schema that didn't exist, which hid real bridge bugs.
_CAMPAIGNS = [
    {
        "campaign_id": "c1",
        "cve_ids": ["CVE-2024-1"],
        "kev_cves": ["CVE-2024-1"],  # confirmed exploitation in the wild
        "report_count": 2,
        "techniques": [
            {
                "technique_id": "T1190",
                "name": "Exploit Public-Facing Application",
                "score": 0.4,
                "corroborations": 3,
            },
            {
                "technique_id": "T1059",
                "name": "Command and Scripting Interpreter",
                "score": 0.3,
                "corroborations": 1,
            },
        ],
        "age_days": 1.4,
    },
    {
        "campaign_id": "c2",
        "cve_ids": ["CVE-2023-9"],
        "kev_cves": [],
        "report_count": 4,
        "techniques": [],
        "age_days": None,
    },
]


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_cyber_evidence_disabled_without_url() -> None:
    assert cyber_evidence(_settings(sentinel_api_url="")) == []


@respx.mock
def test_bridge_maps_real_campaign_schema_to_rated_evidence() -> None:
    respx.get("http://sentinel.test/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(200, json=_CAMPAIGNS)
    )

    bridge = SentinelBridge("http://sentinel.test")
    assert bridge.available() is True
    items = bridge.campaigns_as_evidence(limit=5)
    assert len(items) == 2

    kev = items[0]
    assert kev.doc_id == "sentinel-cyber:c1"
    assert kev.source == "sentinel-cyber" and kev.reliability == "B"
    # technique OBJECTS are reduced to ids — not stringified dicts.
    assert "T1190" in kev.summary and "T1059" in kev.summary
    assert "technique_id" not in kev.summary and "{" not in kev.summary
    # KEV surfaced in the title + summary, and boosts credibility (2 reports -> 3, KEV -> 2).
    assert "[KEV]" in kev.title
    assert "confirmed exploitation in the wild" in kev.summary and "CVE-2024-1" in kev.summary
    assert kev.credibility == 2
    assert "~1d ago" in kev.summary  # recency from age_days

    plain = items[1]
    assert "[KEV]" not in plain.title  # not on KEV
    assert plain.credibility == 1  # 4 reports -> Admiralty 1
    assert "ATT&CK: n/a" in plain.summary and "ago" not in plain.summary  # no techniques/age


def test_bridge_survives_malformed_numeric_fields() -> None:
    # SENTINEL is external input: a stray non-numeric age_days/report_count/score must
    # degrade the field, never raise (the bridge's "never breaks a brief" contract).
    bridge = SentinelBridge("http://sentinel.test")
    campaign = {
        "campaign_id": "cbad",
        "techniques": [{"technique_id": "T1190"}],
        "report_count": "many",  # not an int
        "age_days": "n/a",  # not a float
        "kev_cves": [],
    }
    from unittest.mock import patch

    with patch.object(bridge, "campaigns", return_value=[campaign]):
        items = bridge.campaigns_as_evidence(limit=5)
    assert len(items) == 1
    ev = items[0]
    assert ev.doc_id == "sentinel-cyber:cbad"
    assert "0 CTI reports" in ev.summary  # malformed report_count -> 0, not a crash
    assert "ago" not in ev.summary  # malformed age_days dropped, not a crash


@respx.mock
def test_bridge_annotates_threat_actor_nation() -> None:
    respx.get("http://sentinel.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "campaign_id": "c9",
                    "report_count": 3,
                    "kev_cves": [],
                    "techniques": [],
                    "reports": [{"title": "Sandworm targets the power grid"}],
                }
            ],
        )
    )
    items = SentinelBridge("http://sentinel.test").campaigns_as_evidence(limit=5)
    assert len(items) == 1
    ev = items[0]
    # The named group is resolved to its nation and surfaced in the title + summary, honestly.
    assert "Russia" in ev.title
    assert "Sandworm" in ev.summary and "Russia" in ev.summary and "contested" in ev.summary


@respx.mock
def test_bridge_caps_results_client_side() -> None:
    # SENTINEL's /campaigns has no limit param (returns all); the bridge must cap itself.
    respx.get("http://sentinel.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(200, json=_CAMPAIGNS)
    )
    items = SentinelBridge("http://sentinel.test").campaigns_as_evidence(limit=1)
    assert [i.doc_id for i in items] == ["sentinel-cyber:c1"]


@respx.mock
def test_cyber_evidence_empty_when_unreachable() -> None:
    respx.get("http://sentinel.test/health").mock(return_value=httpx.Response(503))
    assert cyber_evidence(_settings(sentinel_api_url="http://sentinel.test")) == []


def _campaign(cid: str, technique_ids: list[str]) -> dict[str, object]:
    return {
        "campaign_id": cid,
        "cve_ids": [],
        "kev_cves": [],
        "report_count": 2,
        "techniques": [
            {"technique_id": t, "name": t, "score": 0.5, "corroborations": 1} for t in technique_ids
        ],
        "age_days": None,
    }


_RELEVANCE_CAMPAIGNS = [
    _campaign("c1", ["T1190", "T1059"]),  # overlap 2 with a {T1190,T1059} query
    _campaign("c2", ["T1190"]),  # overlap 1
    _campaign("c3", ["T9999"]),  # overlap 0 -> dropped
]


def _mock_graph(map_techniques: object) -> None:
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(200, json=_RELEVANCE_CAMPAIGNS)
    )
    respx.post("http://sentinel.test/map-techniques").mock(return_value=map_techniques)


@respx.mock
def test_query_relevance_filters_and_ranks_by_overlap() -> None:
    # Query maps to T1190 + T1059 (above threshold) and T1036 (below, ignored).
    _mock_graph(
        httpx.Response(
            200,
            json=[
                {"technique_id": "T1190", "name": "x", "score": 0.35, "corroborations": 2},
                {"technique_id": "T1059", "name": "y", "score": 0.30, "corroborations": 1},
                {"technique_id": "T1036", "name": "z", "score": 0.05, "corroborations": 1},
            ],
        )
    )
    items = SentinelBridge("http://sentinel.test").campaigns_as_evidence(
        limit=5, query="exploitation", min_score=0.25
    )
    # c1 (overlap 2) before c2 (overlap 1); c3 (no overlap) dropped entirely.
    assert [i.doc_id for i in items] == ["sentinel-cyber:c1", "sentinel-cyber:c2"]


@respx.mock
def test_query_with_no_relevant_techniques_yields_no_cyber() -> None:
    # Everything the mapper returns is below threshold -> the query isn't cyber -> [].
    _mock_graph(
        httpx.Response(
            200, json=[{"technique_id": "T1036", "name": "z", "score": 0.05, "corroborations": 1}]
        )
    )
    items = SentinelBridge("http://sentinel.test").campaigns_as_evidence(
        limit=5, query="fishing dispute", min_score=0.25
    )
    assert items == []


@respx.mock
def test_mapper_unavailable_falls_back_to_salience() -> None:
    # Mapper down -> keep SENTINEL's salience order rather than suppressing all cyber.
    _mock_graph(httpx.Response(503))
    items = SentinelBridge("http://sentinel.test").campaigns_as_evidence(
        limit=5, query="anything", min_score=0.25
    )
    assert [i.doc_id for i in items] == [
        "sentinel-cyber:c1",
        "sentinel-cyber:c2",
        "sentinel-cyber:c3",
    ]
