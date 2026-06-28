import httpx
import respx

from argus.bridge.sentinel import SentinelBridge, cyber_evidence
from argus.config import Settings

_CAMPAIGNS = [
    {"campaign_id": "c1", "cve_ids": ["CVE-2024-1"], "techniques": ["T1190"], "report_count": 3},
]


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_cyber_evidence_disabled_without_url() -> None:
    assert cyber_evidence(_settings(sentinel_api_url="")) == []


@respx.mock
def test_bridge_maps_campaigns_to_rated_evidence() -> None:
    respx.get("http://sentinel.test/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(200, json=_CAMPAIGNS)
    )

    bridge = SentinelBridge("http://sentinel.test")
    assert bridge.available() is True
    items = bridge.campaigns_as_evidence(limit=5)
    assert len(items) == 1
    ev = items[0]
    assert ev.doc_id == "sentinel-cyber:c1"
    assert ev.source == "sentinel-cyber"
    assert ev.reliability == "B"
    assert ev.credibility == 2  # 3 corroborating reports -> Admiralty 2
    assert ev.summary and "CVE-2024-1" in ev.summary and "T1190" in ev.summary


@respx.mock
def test_cyber_evidence_enabled_end_to_end() -> None:
    respx.get("http://sentinel.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://sentinel.test/campaigns").mock(
        return_value=httpx.Response(200, json=_CAMPAIGNS)
    )
    items = cyber_evidence(_settings(sentinel_api_url="http://sentinel.test"))
    assert [i.doc_id for i in items] == ["sentinel-cyber:c1"]


@respx.mock
def test_cyber_evidence_empty_when_unreachable() -> None:
    respx.get("http://sentinel.test/health").mock(return_value=httpx.Response(503))
    assert cyber_evidence(_settings(sentinel_api_url="http://sentinel.test")) == []
