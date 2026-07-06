import httpx
import pytest
import respx

from argus.ingest.gdelt import (
    fetch_gdelt_articles,
    parse_gdelt_articles,
    sanitize_query,
    simplified_query,
)

GDELT_PAYLOAD = {
    "articles": [
        {
            "url": "https://www.reuters.com/world/asia/story",
            "title": "Naval patrols increase",
            "seendate": "20260627T120000Z",
            "domain": "reuters.com",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
        {
            # no url -> dropped
            "title": "Orphan",
            "domain": "example.com",
        },
    ]
}


def test_parse_gdelt_articles_maps_domain_and_date() -> None:
    docs = parse_gdelt_articles(GDELT_PAYLOAD)
    assert len(docs) == 1  # the url-less article is dropped
    doc = docs[0]
    assert doc.source == "reuters.com"
    assert doc.doc_id.startswith("reuters.com:")
    assert doc.title == "Naval patrols increase"
    assert doc.country == "United Kingdom"
    assert doc.published is not None
    assert doc.published.year == 2026 and doc.published.month == 6
    assert doc.raw is not None and doc.raw["domain"] == "reuters.com"


def test_parse_gdelt_handles_empty_payload() -> None:
    assert parse_gdelt_articles({}) == []
    assert parse_gdelt_articles({"articles": None}) == []


@respx.mock
def test_fetch_gdelt_returns_documents() -> None:
    route = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(200, json=GDELT_PAYLOAD)
    )
    docs = fetch_gdelt_articles("South China Sea")
    assert route.called
    # language filter is appended to the query
    assert "sourcelang:english" in route.calls.last.request.url.params["query"]
    assert len(docs) == 1
    assert docs[0].source == "reuters.com"


@respx.mock
def test_fetch_gdelt_degrades_on_http_error() -> None:
    respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(return_value=httpx.Response(500))
    assert fetch_gdelt_articles("anything") == []


def test_sanitize_query_expands_short_geopolitical_tokens() -> None:
    # GDELT rejects the whole query on any <3-char bare keyword ("US" broke a live ingest).
    assert sanitize_query("US and IRAN dynamics") == '"United States" and IRAN dynamics'
    assert sanitize_query("EU sanctions on X") == '"European Union" sanctions'  # short dropped
    assert sanitize_query("South China Sea") == "South China Sea"  # untouched


def test_simplified_query_keeps_proper_nouns_only() -> None:
    assert simplified_query("US and IRAN dynamics") == '"United States" Iran'
    assert simplified_query("undersea cable sabotage") is None  # no proper nouns
    assert simplified_query("Iran") is None  # wouldn't differ from the sanitized query


@respx.mock
def test_fetch_gdelt_retries_zero_results_with_proper_nouns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("argus.ingest.gdelt.time.sleep", lambda s: None)  # no real rate-wait
    route = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        side_effect=[
            httpx.Response(200, json={"articles": []}),  # over-narrow analyst phrasing
            httpx.Response(200, json=GDELT_PAYLOAD),  # simplified retry hits
        ]
    )
    docs = fetch_gdelt_articles("US and IRAN dynamics")
    assert len(docs) == 1
    assert route.call_count == 2
    first_q = route.calls[0].request.url.params["query"]
    retry_q = route.calls[1].request.url.params["query"]
    assert '"United States" and IRAN dynamics' in first_q
    assert '"United States" Iran' in retry_q and "dynamics" not in retry_q
