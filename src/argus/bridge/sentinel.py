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

from argus.agent.state import EvidenceItem
from argus.config import Settings, get_settings
from argus.logging import get_logger
from argus.nlp.reliability import credibility_from_corroboration

log = get_logger(__name__)


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
        return [r for r in rows if isinstance(r, dict)]

    def campaigns_as_evidence(self, limit: int = 5) -> list[EvidenceItem]:
        """Map SENTINEL campaigns to rated evidence items the analyst can cite.

        SENTINEL's `/campaigns` returns ALL campaigns, already sorted most-salient first
        (actively-exploited → freshest → best-corroborated), with `techniques` as objects
        and `kev_cves`/`age_days` alongside — so we cap client-side, pull the technique ids
        out of the objects, and fold KEV (confirmed exploitation in the wild) and recency
        into both the summary and the credibility.
        """
        items: list[EvidenceItem] = []
        for c in self.campaigns(limit)[:limit]:  # server ignores `limit`; cap here
            cid = str(c.get("campaign_id") or c.get("id") or "?")
            cves = [str(x) for x in (c.get("cve_ids") or [])]
            kev = [str(x) for x in (c.get("kev_cves") or [])]
            techniques = _technique_ids(c.get("techniques") or c.get("technique_ids"))
            report_count = int(c.get("report_count") or len(c.get("reports") or []) or 0)
            age_days = c.get("age_days")

            kev_note = (
                f" KEV: confirmed exploitation in the wild ({', '.join(kev[:3])})." if kev else ""
            )
            age_note = (
                f" Most recent report ~{float(age_days):.0f}d ago." if age_days is not None else ""
            )
            summary = (
                f"SENTINEL cyber campaign linking {report_count} CTI reports. "
                f"CVEs: {', '.join(cves[:5]) or 'n/a'}. "
                f"ATT&CK: {', '.join(techniques[:6]) or 'n/a'}.{kev_note}{age_note}"
            )
            # KEV is real-world corroboration of exploitation — never let it score below the
            # 2-source-corroboration grade.
            credibility = credibility_from_corroboration(report_count)
            if kev:
                credibility = min(credibility, 2)
            items.append(
                EvidenceItem(
                    doc_id=f"sentinel-cyber:{cid}",
                    title=f"Cyber threat campaign {cid}" + (" [KEV]" if kev else ""),
                    source="sentinel-cyber",
                    reliability="B",  # structured CTI from the sibling platform
                    credibility=credibility,
                    summary=summary,
                )
            )
        return items


def cyber_evidence(settings: Settings | None = None, limit: int = 5) -> list[EvidenceItem]:
    """Relevant SENTINEL cyber campaigns as evidence, or [] when the bridge is off."""
    s = settings or get_settings()
    if not s.sentinel_api_url:
        return []
    bridge = SentinelBridge(s.sentinel_api_url, s.http_timeout_seconds)
    if not bridge.available():
        log.warning("sentinel_bridge_unreachable", url=s.sentinel_api_url)
        return []
    return bridge.campaigns_as_evidence(limit)
