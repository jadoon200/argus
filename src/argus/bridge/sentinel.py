"""Cyber-fusion bridge — read-only client for the sibling SENTINEL knowledge graph.

This is the join that makes ARGUS *all-source*: when `ARGUS_SENTINEL_API_URL` is set,
the analyst's evidence is augmented with relevant cyber threat campaigns from SENTINEL's
read-only API, so one brief can reason across the open-source picture AND the cyber one —
the way a fusion cell does. ARGUS only ever READS from SENTINEL; the cyber graph stays
SENTINEL's system of record. Disabled (returns nothing) when the URL is unset or the API
is unreachable, so the bridge never breaks a brief.
"""

from typing import Any

import httpx

from argus.actors import attributions_in_text
from argus.agent.state import EvidenceItem
from argus.config import Settings, get_settings
from argus.logging import get_logger
from argus.nlp.reliability import credibility_from_corroboration

log = get_logger(__name__)


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce an upstream field to int, defaulting on a missing/malformed value — SENTINEL
    is external input, so a stray non-numeric must degrade the field, never break a brief."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    """Coerce an upstream field to float, or None on a missing/malformed value."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _campaign_text(c: dict[str, Any]) -> str:
    """The free-text of a campaign to scan for threat-actor names (name/description + report
    titles), so a named group can be resolved to its nation attribution."""
    parts = [str(c.get(k) or "") for k in ("name", "title", "label", "description", "summary")]
    parts += [str(r.get("title") or "") for r in (c.get("reports") or []) if isinstance(r, dict)]
    return " ".join(p for p in parts if p)


def _technique_ids(techniques: Any) -> list[str]:
    """Pull ATT&CK ids out of SENTINEL's `techniques` — a list of `{technique_id, name,
    score, corroborations}` objects — while tolerating a bare-string form too."""
    out: list[str] = []
    for t in techniques or []:
        if isinstance(t, dict):
            tid = t.get("technique_id") or t.get("id")
            if tid:
                out.append(str(tid))
        elif t:
            out.append(str(t))
    return out


class SentinelBridge:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._url = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = httpx.get(f"{self._url}{path}", params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        resp = httpx.post(f"{self._url}{path}", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def map_techniques(self, text: str, min_score: float = 0.0) -> list[str] | None:
        """ATT&CK technique ids SENTINEL's zero-shot mapper finds in `text` (score >=
        `min_score`). Returns ``None`` if the mapper is unavailable — so the caller can fall
        back to salience order rather than wrongly suppressing all cyber evidence."""
        try:
            data = self._post("/map-techniques", {"text": text})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("sentinel_map_techniques_failed", error=str(exc))
            return None
        if not isinstance(data, list):
            return None
        return [
            str(m["technique_id"])
            for m in data
            if isinstance(m, dict)
            and m.get("technique_id")
            and (_as_float(m.get("score")) or 0.0) >= min_score
        ]

    def available(self) -> bool:
        try:
            self._get("/health")
            return True
        except (httpx.HTTPError, ValueError):
            return False

    def campaigns(self, limit: int) -> list[dict[str, Any]]:
        try:
            data = self._get("/campaigns", {"limit": limit})
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("sentinel_bridge_failed", error=str(exc))
            return []
        rows = data if isinstance(data, list) else data.get("campaigns", [])
        # SENTINEL ignores `limit` and returns every campaign (salience-ordered); enforce
        # the cap client-side so an unbounded upstream can't balloon a /brief's work.
        return [r for r in rows if isinstance(r, dict)][:limit]

    def stats(self) -> dict[str, Any] | None:
        """SENTINEL summary counts for the cached ARGUS overview, or None on failure."""
        try:
            data = self._get("/stats")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("sentinel_stats_failed", error=str(exc))
            return None
        return data if isinstance(data, dict) else None

    def _rank_by_relevance(
        self, campaigns: list[dict[str, Any]], query: str, min_score: float
    ) -> list[dict[str, Any]]:
        """Keep only campaigns whose ATT&CK techniques overlap the techniques SENTINEL maps
        the `query` to, ranked by overlap. Mapper down → keep salience order (don't suppress);
        query maps to no cyber techniques → no cyber evidence (the brief just isn't cyber)."""
        relevant = self.map_techniques(query, min_score)
        if relevant is None:
            return campaigns
        if not relevant:
            return []
        relevant_set = set(relevant)
        scored: list[tuple[int, dict[str, Any]]] = []
        for c in campaigns:
            techs = set(_technique_ids(c.get("techniques") or c.get("technique_ids")))
            overlap = len(techs & relevant_set)
            if overlap:
                scored.append((overlap, c))
        scored.sort(key=lambda x: -x[0])  # stable: SENTINEL's salience order breaks ties
        return [c for _, c in scored]

    def campaigns_as_evidence(
        self, limit: int = 5, query: str | None = None, min_score: float = 0.0
    ) -> list[EvidenceItem]:
        """Map SENTINEL campaigns to rated evidence items the analyst can cite.

        SENTINEL's `/campaigns` returns ALL campaigns, already sorted most-salient first
        (actively-exploited → freshest → best-corroborated), with `techniques` as objects
        and `kev_cves`/`age_days` alongside — so we cap client-side, pull the technique ids
        out of the objects, and fold KEV (confirmed exploitation in the wild) and recency
        into both the summary and the credibility. With a `query`, only campaigns relevant
        to it (technique overlap via SENTINEL's mapper) are kept.
        """
        # With a query the relevance filter runs *after* the fetch, so pull a deeper
        # salience-ordered pool first — otherwise a query-relevant campaign outside the
        # top-`limit` most-salient would be silently dropped.
        campaigns = self.campaigns(limit * 10 if query else limit)
        if query:
            campaigns = self._rank_by_relevance(campaigns, query, min_score)
        items: list[EvidenceItem] = []
        for c in campaigns[:limit]:  # server ignores `limit`; cap here
            cid = str(c.get("campaign_id") or c.get("id") or "?")
            cves = [str(x) for x in (c.get("cve_ids") or [])]
            kev = [str(x) for x in (c.get("kev_cves") or [])]
            techniques = _technique_ids(c.get("techniques") or c.get("technique_ids"))
            report_count = _as_int(c.get("report_count")) or len(c.get("reports") or [])
            age_days = _as_float(c.get("age_days"))

            kev_note = (
                f" KEV: confirmed exploitation in the wild ({', '.join(kev[:3])})." if kev else ""
            )
            age_note = f" Most recent report ~{age_days:.0f}d ago." if age_days is not None else ""
            # Cross-graph join: resolve any threat group named in the campaign to its nation
            # attribution, so a cyber campaign links to the geopolitical actor of the brief.
            actors = attributions_in_text(_campaign_text(c))
            nations = sorted({a.nation for a in actors})
            attr_note = (
                f" Attributed in open reporting to {', '.join(a.name for a in actors)} "
                f"({', '.join(nations)}) — contested, human-review."
                if actors
                else ""
            )
            summary = (
                f"SENTINEL cyber campaign linking {report_count} CTI reports. "
                f"CVEs: {', '.join(cves[:5]) or 'n/a'}. "
                f"ATT&CK: {', '.join(techniques[:6]) or 'n/a'}.{kev_note}{age_note}{attr_note}"
            )
            # KEV is real-world corroboration of exploitation — never let it score below the
            # 2-source-corroboration grade.
            credibility = credibility_from_corroboration(report_count)
            if kev:
                credibility = min(credibility, 2)
            title = f"Cyber threat campaign {cid}" + (" [KEV]" if kev else "")
            if nations:
                title += f" — {', '.join(nations)}"
            items.append(
                EvidenceItem(
                    doc_id=f"sentinel-cyber:{cid}",
                    title=title,
                    source="sentinel-cyber",
                    reliability="B",  # structured CTI from the sibling platform
                    credibility=credibility,
                    summary=summary,
                )
            )
        return items


def cyber_evidence(
    settings: Settings | None = None, limit: int = 5, query: str | None = None
) -> list[EvidenceItem]:
    """SENTINEL cyber campaigns relevant to `query` as evidence, or [] when the bridge is
    off. With no `query` (or `sentinel_relevance_min_score=0`) returns the top-salient
    campaigns; with one, only campaigns whose techniques relate to the query."""
    s = settings or get_settings()
    if not s.sentinel_api_url:
        return []
    bridge = SentinelBridge(s.sentinel_api_url, s.sibling_timeout_seconds)
    if not bridge.available():
        log.warning("sentinel_bridge_unreachable", url=s.sentinel_api_url)
        return []
    relevance_query = query if s.sentinel_relevance_min_score > 0 else None
    return bridge.campaigns_as_evidence(
        limit, query=relevance_query, min_score=s.sentinel_relevance_min_score
    )
