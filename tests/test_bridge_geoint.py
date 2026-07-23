import httpx
import respx

from argus.bridge.geoint import GeointBridge, air_evidence, geoint_evidence, maritime_evidence
from argus.config import Settings

# Mirrors PHAROS's real /geoint/evidence rows (pharos.geoint.to_evidence): EvidenceItem
# fields 1:1 plus geospatial extras the bridge may ignore. `url` is relative (resolvable
# on the PHAROS API), reliability is the AIS-confidence Admiralty grade.
_EVIDENCE = [
    {
        "doc_id": "gap-563012345-20260701",
        "title": "Dark ship (AIS gap) - MMSI 563012345",
        "source": "PHAROS maritime domain awareness",
        "reliability": "C",
        "credibility": 3,
        "summary": (
            "Dark ship (AIS gap): MMSI 563012345 in the Singapore Strait — silent 720 min, "
            "reappearing 41 km displaced. Human-review decision support, not a verdict. "
            "A gap may be benign coverage loss."
        ),
        "published": "2026-07-01T04:10:00",
        "url": "/incidents/gap-563012345-20260701",
        "kind": "geoint",
        "detector": "gap",
        "mmsi": 563012345,
        "counterpart_mmsi": None,
        "lat": 1.2,
        "lon": 103.8,
        "zone": "Singapore Strait",
        "techniques": ["MT-GAP"],
        "region": "sg",
    },
    {
        "doc_id": "rdv-9-20260702",
        "title": "Ship-to-ship transfer - MMSI 512000001",
        "source": "PHAROS maritime domain awareness",
        "reliability": "B",
        "credibility": 2,
        "summary": "Ship-to-ship transfer: MMSI 512000001 with MMSI 512000002 for 95 min.",
        "published": "2026-07-02T09:00:00",
        "url": "/incidents/rdv-9-20260702",
        "kind": "geoint",
        "detector": "rendezvous",
        "zone": None,
        "region": "sg",
    },
]


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def _mock_api(rows: object = None) -> None:
    respx.get("http://pharos.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://pharos.test/geoint/evidence").mock(
        return_value=httpx.Response(200, json=_EVIDENCE if rows is None else rows)
    )


def test_lanes_disabled_without_url() -> None:
    assert geoint_evidence(_settings(pharos_api_url="", horus_api_url="")) == []
    assert maritime_evidence(_settings(pharos_api_url="")) == []
    assert air_evidence(_settings(horus_api_url="")) == []


@respx.mock
def test_geoint_evidence_empty_when_unreachable() -> None:
    respx.get("http://pharos.test/health").mock(return_value=httpx.Response(503))
    assert maritime_evidence(_settings(pharos_api_url="http://pharos.test")) == []


@respx.mock
def test_bridge_maps_real_geoint_schema_to_rated_evidence() -> None:
    _mock_api()
    bridge = GeointBridge("http://pharos.test", "pharos-geoint")
    assert bridge.available() is True
    items = bridge.incidents_as_evidence(limit=5)
    assert len(items) == 2

    gap = items[0]
    # Re-keyed like the cyber lane (sentinel-cyber:*) so the UI/citations can tag the lane.
    assert gap.doc_id == "pharos-geoint:gap-563012345-20260701"
    assert gap.source == "pharos-geoint"
    # PHAROS's Admiralty grades pass through untouched — the AIS-confidence rating IS the point.
    assert gap.reliability == "C" and gap.credibility == 3
    # The relative incident link is made absolute so a citation resolves outside PHAROS.
    assert gap.url == "http://pharos.test/incidents/gap-563012345-20260701"
    assert gap.summary is not None
    assert "Human-review" in gap.summary
    # Zone context is appended for the analyst even though it arrives as an extra field.
    assert "Singapore Strait" in gap.summary

    rdv = items[1]
    assert rdv.reliability == "B" and rdv.credibility == 2


@respx.mock
def test_bridge_survives_malformed_rows() -> None:
    # PHAROS is external input: junk rows/fields must degrade, never break a brief.
    _mock_api(
        [
            "not-a-dict",
            {"title": "no doc_id -> uncitable"},
            {"doc_id": "x1", "title": ""},  # no renderable title -> dropped
            {
                "doc_id": "ok-1",
                "title": "Loitering - MMSI 1",
                "reliability": "Z",  # not a grade -> F (conservative unknown)
                "credibility": "high",  # not an int -> None
                "url": None,
            },
        ]
    )
    items = GeointBridge("http://pharos.test", "pharos-geoint").incidents_as_evidence(limit=5)
    assert [i.doc_id for i in items] == ["pharos-geoint:ok-1"]
    ev = items[0]
    assert ev.reliability == "F" and ev.credibility is None and ev.url is None


@respx.mock
def test_bridge_caps_results_client_side() -> None:
    # A misbehaving upstream ignoring `limit` must still be truncated client-side.
    _mock_api(
        [
            {"doc_id": f"i{n}", "title": f"Incident {n}", "reliability": "C", "credibility": 4}
            for n in range(300)
        ]
    )
    assert (
        len(GeointBridge("http://pharos.test", "pharos-geoint").incidents_as_evidence(limit=5)) == 5
    )


@respx.mock
def test_query_relevance_keeps_maritime_drops_unrelated() -> None:
    _mock_api()
    bridge = GeointBridge("http://pharos.test", "pharos-geoint")
    # A maritime question shares subject tokens with the incident evidence ("ship" keeps
    # both the dark-ship gap and the ship-to-ship transfer — one shared token is enough).
    maritime = bridge.incidents_as_evidence(limit=5, query="dark ship in the Singapore Strait")
    assert [i.doc_id for i in maritime] == [
        "pharos-geoint:gap-563012345-20260701",
        "pharos-geoint:rdv-9-20260702",
    ]
    # A narrower question about vessels going dark keeps only the gap incident.
    dark_only = bridge.incidents_as_evidence(limit=5, query="vessels going dark near Singapore")
    assert [i.doc_id for i in dark_only] == ["pharos-geoint:gap-563012345-20260701"]
    # A non-maritime question pulls no maritime evidence at all.
    assert bridge.incidents_as_evidence(limit=5, query="parliamentary election results") == []


@respx.mock
def test_subjectless_query_keeps_everything() -> None:
    # "any updates?" has no subject tokens — relevance is unknowable, not zero (triage contract).
    _mock_api()
    items = GeointBridge("http://pharos.test", "pharos-geoint").incidents_as_evidence(
        limit=5, query="any updates?"
    )
    assert len(items) == 2


# --- the air lane (HORUS) — same contract, different source key ------------------------
_AIR_EVIDENCE = [
    {
        "doc_id": "jam:2:207:14",
        "title": "GNSS interference - Singapore Strait Overwater Corridor",
        "source": "HORUS air domain awareness",
        "reliability": "C",
        "credibility": 2,
        "summary": (
            "GNSS interference: area-level signal in the Singapore Strait Overwater Corridor "
            "— 5/7 aircraft degraded (worst-NIC cluster). Human-review decision support, "
            "not a verdict."
        ),
        "published": "2026-07-23T16:20:00",
        "url": "/incidents/jam:2:207:14",
        "kind": "geoint-air",
        "detector": "jamming",
        "icao24": None,
        "zone": "Singapore Strait Overwater Corridor",
    }
]


@respx.mock
def test_air_lane_uses_the_same_client_with_its_own_key() -> None:
    respx.get("http://horus.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://horus.test/geoint/evidence").mock(
        return_value=httpx.Response(200, json=_AIR_EVIDENCE)
    )
    (item,) = air_evidence(_settings(horus_api_url="http://horus.test"))
    # Re-keyed by lane so citations stay unambiguous when lanes are fused.
    assert item.doc_id == "horus-geoint:jam:2:207:14"
    assert item.source == "horus-geoint"
    assert item.reliability == "C" and item.credibility == 2
    assert item.url == "http://horus.test/incidents/jam:2:207:14"


@respx.mock
def test_both_geospatial_lanes_fuse_into_one_evidence_set() -> None:
    # The four-lane claim, minimally: one call returns maritime AND air evidence, each
    # carrying its own source rating and a distinct citable id.
    _mock_api()
    respx.get("http://horus.test/health").mock(return_value=httpx.Response(200, json={}))
    respx.get("http://horus.test/geoint/evidence").mock(
        return_value=httpx.Response(200, json=_AIR_EVIDENCE)
    )
    items = geoint_evidence(
        _settings(pharos_api_url="http://pharos.test", horus_api_url="http://horus.test")
    )
    sources = {i.source for i in items}
    assert sources == {"pharos-geoint", "horus-geoint"}
    assert len({i.doc_id for i in items}) == len(items)  # no id collisions across lanes


@respx.mock
def test_one_lane_down_never_suppresses_the_other() -> None:
    # A dead sibling must degrade to silence for its own lane only — never break a brief.
    _mock_api()
    respx.get("http://horus.test/health").mock(return_value=httpx.Response(503))
    items = geoint_evidence(
        _settings(pharos_api_url="http://pharos.test", horus_api_url="http://horus.test")
    )
    assert items and {i.source for i in items} == {"pharos-geoint"}
