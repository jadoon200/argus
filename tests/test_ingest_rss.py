import httpx
import respx

from argus.ingest.rss import fetch_rss_documents, parse_feed

RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example World</title>
    <item>
      <title>Tensions rise in disputed waters</title>
      <link>https://example.com/a</link>
      <description>A &lt;b&gt;short&lt;/b&gt; summary.</description>
      <pubDate>Fri, 20 Jun 2026 09:00:00 GMT</pubDate>
      <category>asia</category>
      <category>security</category>
    </item>
    <item>
      <link>https://example.com/no-title</link>
    </item>
  </channel>
</rss>"""

ATOM_SAMPLE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <entry>
    <title>Summit concludes</title>
    <link rel="replies" href="https://example.com/x/replies"/>
    <link rel="alternate" href="https://example.com/x"/>
    <summary>Leaders met.</summary>
    <published>2026-06-21T10:00:00Z</published>
    <category term="diplomacy"/>
  </entry>
</feed>"""


def test_parse_rss_extracts_fields_and_tags() -> None:
    docs = parse_feed(RSS_SAMPLE, source="bbc-world")
    assert len(docs) == 1  # the second item has no title and is skipped
    doc = docs[0]
    assert doc.source == "bbc-world"
    assert doc.doc_id.startswith("bbc-world:")
    assert doc.title == "Tensions rise in disputed waters"
    assert doc.summary == "A short summary."  # tags stripped, entities unescaped
    assert doc.url == "https://example.com/a"
    assert doc.tags == ["asia", "security"]
    assert doc.published is not None


def test_parse_atom_prefers_alternate_link() -> None:
    docs = parse_feed(ATOM_SAMPLE, source="reliefweb")
    assert len(docs) == 1
    assert docs[0].url == "https://example.com/x"  # not the rel="replies" link
    assert docs[0].tags == ["diplomacy"]


def test_parse_feed_rejects_unknown_root() -> None:
    try:
        parse_feed("<html><body>not a feed</body></html>", source="x")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for non-feed root")


@respx.mock
def test_fetch_rss_skips_broken_feed() -> None:
    respx.get("https://good.example/feed").mock(return_value=httpx.Response(200, text=RSS_SAMPLE))
    respx.get("https://bad.example/feed").mock(return_value=httpx.Response(503))
    docs = fetch_rss_documents(
        {"good": "https://good.example/feed", "bad": "https://bad.example/feed"}
    )
    # One good feed yields its document; the broken feed is skipped, not fatal.
    assert len(docs) == 1
    assert docs[0].source == "good"
