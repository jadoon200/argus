import httpx
import respx

from argus.ingest.gdelt import fetch_gdelt_articles, parse_gdelt_articles

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
