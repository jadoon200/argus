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
