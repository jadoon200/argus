"""GEOINT-fusion bridge — read-only client for the sibling PHAROS maritime picture.

The third lane of the all-source join: when `ARGUS_PHAROS_API_URL` is set, the analyst's
evidence is augmented with maritime incidents from PHAROS's read-only `/geoint/evidence`
endpoint — dark ships, ship-to-ship transfers, loitering, spoofing, trajectory anomalies —
so one brief reasons across open-source reporting, the cyber picture (SENTINEL), AND the
geospatial one. PHAROS already shapes each incident to ARGUS's `EvidenceItem` fields
(doc_id / title / source / reliability A-F / credibility 1-6 / summary / published / url),
so this bridge validates and re-keys rather than translates. ARGUS only ever READS from
PHAROS; the maritime graph stays PHAROS's system of record. Disabled (returns nothing)
when the URL is unset or the API is unreachable, so the bridge never breaks a brief.

Query relevance: PHAROS has no technique mapper to route through (SENTINEL's ATT&CK trick),
so the gate is the deterministic subject-token overlap already used by triage — a maritime
question ("dark ships in the Singapore Strait?") shares tokens with incident evidence, a
purely political one doesn't and pulls no maritime items. Subject-less queries keep
everything (relevance is unknowable, not zero — same contract as triage).
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
    """Coerce an upstream credibility to the Admiralty 1-6 range, or None — PHAROS is
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


class PharosBridge:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._url = base_url.rstrip("/")
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
            log.warning("pharos_bridge_failed", error=str(exc))
            return []
        if not isinstance(data, list):
            return []
        # PHAROS honours `limit` server-side (score-ordered, riskiest first), but cap
        # client-side too so a misbehaving upstream can't balloon a /brief's work.
        return [r for r in data if isinstance(r, dict)][:limit]

    def _to_item(self, row: dict[str, Any]) -> EvidenceItem | None:
        doc_id = str(row.get("doc_id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not doc_id or not title:
            return None  # uncitable without a stable id and a renderable title
        url = str(row.get("url") or "") or None
        if url and url.startswith("/"):
            url = f"{self._url}{url}"  # PHAROS serves relative incident links; make citable
        zone = row.get("zone")
        zone_note = f" Zone: {zone}." if zone else ""
        summary = str(row.get("summary") or "").strip() or None
        return EvidenceItem(
            doc_id=f"pharos-geoint:{doc_id}",
            title=title,
            source="pharos-geoint",
            reliability=_as_reliability(row.get("reliability")),
            credibility=_as_credibility(row.get("credibility")),
            summary=f"{summary or title}{zone_note}",
            published=str(row.get("published") or "") or None,
            url=url,
        )

    def incidents_as_evidence(self, limit: int = 5, query: str | None = None) -> list[EvidenceItem]:
        """Map PHAROS maritime incidents to rated evidence items the analyst can cite.

        With a `query`, only incidents sharing a subject token with it are kept (the
        deterministic triage gate), so a non-maritime brief pulls no maritime evidence.
        The relevance filter runs over a deeper score-ordered pool first — otherwise a
        query-relevant incident outside the top-`limit` riskiest would be silently dropped.
        """
        rows = self.incidents(limit * 10 if query else limit)
        items = [item for row in rows if (item := self._to_item(row)) is not None]
        if query:
            items = [i for i in items if relevant_count(query, [i]) > 0]
        return items[:limit]


def geoint_evidence(
    settings: Settings | None = None, limit: int = 5, query: str | None = None
) -> list[EvidenceItem]:
    """PHAROS maritime incidents relevant to `query` as evidence, or [] when the bridge
    is off. With no `query` returns the riskiest incidents in PHAROS's score order."""
    s = settings or get_settings()
    if not s.pharos_api_url:
        return []
    bridge = PharosBridge(s.pharos_api_url, s.http_timeout_seconds)
    if not bridge.available():
        log.warning("pharos_bridge_unreachable", url=s.pharos_api_url)
        return []
    return bridge.incidents_as_evidence(limit, query=query)
