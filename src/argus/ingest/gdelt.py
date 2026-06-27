"""GDELT DOC 2.0 API client — query-driven open-source news collection.

GDELT indexes worldwide news in near-real-time and exposes a free, keyless article
search (the DOC 2.0 `ArtList` mode). Given an analyst query, we pull recent matching
articles and turn each into a Document tagged with its publishing domain as the
provenance source. https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.config import get_settings
from argus.db.models import Document
from argus.logging import get_logger

log = get_logger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; ARGUS-OSINT/0.1; +https://github.com/jaydenOoOo)"


def _doc_id(source: str, url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    return f"{source}:{digest}"


def _parse_seendate(value: str | None) -> datetime | None:
    """GDELT seendate is compact UTC, e.g. '20260627T120000Z'."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def parse_gdelt_articles(payload: dict[str, Any]) -> list[Document]:
    """Turn a DOC 2.0 ArtList JSON payload into Documents (source = article domain)."""
    docs: list[Document] = []
    for art in payload.get("articles", []) or []:
        url = art.get("url")
        if not url:
            continue
        source = (art.get("domain") or "gdelt").lower()
        docs.append(
            Document(
                doc_id=_doc_id(source, url),
                source=source,
                title=art.get("title") or url,
                summary=None,  # ArtList carries no snippet; enrichment fills context
                url=url,
                language=art.get("language"),
                country=art.get("sourcecountry"),
                published=_parse_seendate(art.get("seendate")),
                raw=art,
            )
        )
    return docs


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)
def _fetch(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = client.get(url, params=params)
    response.raise_for_status()
    # GDELT returns HTML (not JSON) for malformed queries — let ValueError surface.
    return response.json()  # type: ignore[no-any-return]


def fetch_gdelt_articles(
    query: str,
    max_records: int | None = None,
    timespan: str | None = None,
) -> list[Document]:
    """Fetch recent articles matching `query` (most recent first).

    Returns [] on any HTTP/parse failure — collection degrades, never crashes.
    """
    settings = get_settings()
    q = query.strip()
    if settings.gdelt_source_lang:
        q = f"{q} sourcelang:{settings.gdelt_source_lang}"
    params: dict[str, Any] = {
        "query": q,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": max_records or settings.gdelt_max_records,
        "timespan": timespan or settings.gdelt_timespan,
        "sort": "DateDesc",
    }
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers) as client:
        try:
            payload = _fetch(client, settings.gdelt_api_url, params)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("gdelt_fetch_failed", query=query, error=str(exc))
            return []
    return parse_gdelt_articles(payload)
