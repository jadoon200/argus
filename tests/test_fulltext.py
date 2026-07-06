import httpx
import respx

from argus.db.models import Document
from argus.nlp.fulltext import (
    extract_main_text,
    hydrate_documents,
    needs_text,
    reembed_documents,
)

_PAGE = """
<html><head><script>tracking();</script><style>.x{}</style></head>
<body>
  <nav><p>Home News Sport Weather and lots of other navigation words here to skip</p></nav>
  <article>
    <p>Iranian and United States negotiators concluded a third round of indirect talks in
    Muscat on Sunday, with both delegations describing the discussions as substantive.</p>
    <p>Sign up</p>
    <p>The talks covered sanctions relief and uranium enrichment limits, according to two
    officials familiar with the negotiations who spoke on condition of anonymity.</p>
  </article>
  <footer><p>Copyright notice and cookie preferences and subscription offers text block</p></footer>
</body></html>
"""


def test_extract_main_text_keeps_prose_drops_boilerplate() -> None:
    text = extract_main_text(_PAGE)
    assert "third round of indirect talks in Muscat" in text
    assert "sanctions relief and uranium enrichment" in text
    assert "Sign up" not in text  # short non-prose dropped
    assert "tracking" not in text and "Copyright" not in text  # script/footer stripped


def test_extract_main_text_handles_junk() -> None:
    assert extract_main_text("") == ""
    assert extract_main_text("<html><body>no paragraphs here</body></html>") == ""
    long_para = "<p>" + "word " * 800 + "</p>"
    assert len(extract_main_text(f"<article>{long_para}</article>")) <= 1800


def _doc(doc_id: str, url: str | None, summary: str | None = None) -> Document:
    return Document(doc_id=doc_id, source="s", title="Headline only", url=url, summary=summary)


def test_needs_text() -> None:
    assert needs_text(_doc("a:1", "https://x.test/a"))
    assert not needs_text(_doc("a:2", None))  # no URL to fetch
    assert not needs_text(_doc("a:3", "https://x.test/b", "s" * 200))  # already has text


@respx.mock
def test_hydrate_documents_sets_summary_and_clears_embedding() -> None:
    respx.get("https://x.test/ok").mock(return_value=httpx.Response(200, text=_PAGE))
    respx.get("https://x.test/down").mock(return_value=httpx.Response(500))
    ok = _doc("a:1", "https://x.test/ok")
    ok.embedding = [1.0, 0.0]
    down = _doc("a:2", "https://x.test/down")
    skipped = _doc("a:3", "https://x.test/skip", summary="s" * 200)

    hydrated = hydrate_documents([ok, down, skipped])
    assert hydrated == 1
    assert ok.summary and "Muscat" in ok.summary
    assert ok.embedding is None  # stale headline embedding cleared for re-embed
    assert down.summary is None  # failure leaves the doc as it was
    assert skipped.summary == "s" * 200


@respx.mock
def test_hydrate_respects_limit() -> None:
    route = respx.get("https://x.test/ok").mock(return_value=httpx.Response(200, text=_PAGE))
    docs = [_doc(f"a:{i}", "https://x.test/ok") for i in range(5)]
    hydrate_documents(docs, limit=2)
    assert route.call_count == 2


def test_reembed_uses_new_text(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_embed(texts: list[str]):
        calls.append(texts)
        return [[0.5, 0.5] for _ in texts]

    monkeypatch.setattr("argus.nlp.embed.embed_texts", fake_embed)
    doc = _doc("a:1", "https://x.test/a", summary="Real article text about the Muscat talks.")
    doc.embedding = None
    reembed_documents([doc])
    assert doc.embedding == [0.5, 0.5]
    assert "Muscat talks" in calls[0][0]  # embedded over the hydrated text
