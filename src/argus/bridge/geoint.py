"""GEOINT-fusion bridge — read-only client for the Sky and Ocean sibling lanes.

The third and fourth lanes of the all-source join. PHAROS (Ocean) and HORUS (Sky) both
expose `GET /geoint/evidence`, and both already shape each incident to ARGUS's
`EvidenceItem` fields (doc_id / title / source / reliability A-F / credibility 1-6 /
summary / published / url). Because that contract is identical by design, one client serves
both: this bridge validates and re-keys rather than translates, and adding a further
geospatial sibling is a URL plus a source key.

So a brief can reason across open-source reporting, the cyber picture (SENTINEL), the
Ocean picture (PHAROS) and the Sky picture (HORUS) at once — each item carrying its own
source rating. ARGUS only ever READS; each sibling stays the system of record for its lane.
Disabled (returns nothing) when the URL is unset or the API is unreachable, so a bridge
never breaks a brief.

Query relevance: neither sibling has a technique mapper to route through (SENTINEL's ATT&CK
trick), so the gate is the deterministic subject-token overlap already used by triage — a
maritime or air question shares tokens with incident evidence, a purely political one
doesn't and pulls nothing. Subject-less queries keep everything (relevance is unknowable,
not zero — same contract as triage).
"""

from typing import Any

import httpx

from argus.agent.state import EvidenceItem
from argus.agent.triage import relevant_count
from argus.config import Settings, get_settings
from argus.logging import get_logger

log = get_logger(__name__)

_RELIABILITY_GRADES = frozenset("ABCDEF")


def _as_credibility(value: Any) -> int | None:
    """Coerce an upstream credibility to the Admiralty 1-6 range, or None — a sibling is
    external input, so a stray non-numeric must degrade the field, never break a brief."""
    try:
        c = int(value)
    except (TypeError, ValueError):
        return None
    return c if 1 <= c <= 6 else None


def _as_reliability(value: Any) -> str:
    """Validate an upstream Admiralty reliability grade; unknown/malformed -> F
    (the conservative unknown-source convention from `argus.sources`)."""
    grade = str(value or "").strip().upper()
    return grade if grade in _RELIABILITY_GRADES else "F"


class GeointBridge:
    """Read-only client for a sibling that serves ARGUS-shaped GEOINT evidence.

    `source_key` labels the lane ("ocean-geoint", "sky-geoint"); it prefixes every doc_id
    so citations stay unambiguous across lanes and the dashboard can tag their origin.
    """

    def __init__(self, base_url: str, source_key: str, timeout: float = 10.0) -> None:
        self._url = base_url.rstrip("/")
        self._source = source_key
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = httpx.get(f"{self._url}{path}", params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def available(self) -> bool:
        try:
            self._get("/health")
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def incidents(self, limit: int) -> list[dict[str, Any]]:
        try:
            data = self._get("/geoint/evidence", {"limit": limit})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("geoint_bridge_failed", source=self._source, error=str(exc))
            return []
        if not isinstance(data, list):
            return []
        # Siblings honour `limit` server-side (score-ordered, riskiest first), but cap
        # client-side too so a misbehaving upstream can't balloon a /brief's work.
        return [r for r in data if isinstance(r, dict)][:limit]

    def stats(self) -> dict[str, Any] | None:
        """Sibling summary counts for the cached ARGUS overview, or None when unavailable."""
        try:
            data = self._get("/stats")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("geoint_stats_failed", source=self._source, error=str(exc))
            return None
        return data if isinstance(data, dict) else None

    def _to_item(self, row: dict[str, Any]) -> EvidenceItem | None:
        doc_id = str(row.get("doc_id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not doc_id or not title:
            return None  # uncitable without a stable id and a renderable title
        url = str(row.get("url") or "") or None
        if url and url.startswith("/"):
            url = f"{self._url}{url}"  # siblings serve relative links; make citable
        zone = row.get("zone")
        zone_note = f" Zone: {zone}." if zone else ""
        summary = str(row.get("summary") or "").strip() or None
        return EvidenceItem(
            doc_id=f"{self._source}:{doc_id}",
            title=title,
            source=self._source,
            reliability=_as_reliability(row.get("reliability")),
            credibility=_as_credibility(row.get("credibility")),
            summary=f"{summary or title}{zone_note}",
            published=str(row.get("published") or "") or None,
            url=url,
        )

    def incidents_as_evidence(self, limit: int = 5, query: str | None = None) -> list[EvidenceItem]:
        """Map a sibling's incidents to rated evidence items the analyst can cite.

        With a `query`, only incidents sharing a subject token with it are kept (the
        deterministic triage gate), so an unrelated brief pulls no geospatial evidence.
        The relevance filter runs over a deeper score-ordered pool first — otherwise a
        query-relevant incident outside the top-`limit` riskiest would be silently dropped.
        """
        rows = self.incidents(limit * 10 if query else limit)
        items = [item for row in rows if (item := self._to_item(row)) is not None]
        if query:
            items = [i for i in items if relevant_count(query, [i]) > 0]
        return items[:limit]


def _lane_evidence(
    url: str, source_key: str, settings: Settings, limit: int, query: str | None
) -> list[EvidenceItem]:
    if not url:
        return []
    bridge = GeointBridge(url, source_key, settings.http_timeout_seconds)
    if not bridge.available():
        log.warning("geoint_bridge_unreachable", source=source_key, url=url)
        return []
    return bridge.incidents_as_evidence(limit, query=query)


def ocean_evidence(
    settings: Settings | None = None, limit: int = 5, query: str | None = None
) -> list[EvidenceItem]:
    """PHAROS Ocean incidents relevant to `query`, or [] when that bridge is off."""
    s = settings or get_settings()
    return _lane_evidence(s.pharos_api_url, "ocean-geoint", s, limit, query)


def sky_evidence(
    settings: Settings | None = None, limit: int = 5, query: str | None = None
) -> list[EvidenceItem]:
    """HORUS Sky incidents relevant to `query`, or [] when that bridge is off."""
    s = settings or get_settings()
    return _lane_evidence(s.horus_api_url, "sky-geoint", s, limit, query)


def geoint_evidence(
    settings: Settings | None = None, limit: int = 5, query: str | None = None
) -> list[EvidenceItem]:
    """Every configured geospatial lane's evidence for `query` (Ocean + Sky)."""
    s = settings or get_settings()
    return ocean_evidence(s, limit, query) + sky_evidence(s, limit, query)
