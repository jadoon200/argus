"""Full-text hydration — give the analyst article text, not headlines.

GDELT's ArtList returns titles only, so roughly half the corpus is a bare headline; a
brief written over a dozen ten-word titles reads as vague, hedged filler no matter how
good the model is (live-reported: "the content is lackluster"). This module fetches the
article behind a Document's URL and extracts the main body text — dependency-free (no
readability/trafilatura), because a rough paragraph heuristic over real text beats a
perfect extraction of nothing.

Hydration runs in two places, both best-effort and bounded:
- at collection time for newly ingested documents (before enrichment, so embeddings and
  events are computed over real text), and
- at evidence-gathering time for any headline-only document selected for a brief (a
  backstop for docs ingested before this existed).

A fetch failure leaves the document as it was — the title is still evidence.
"""

import html as html_lib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import httpx

from argus.config import get_settings
from argus.logging import get_logger

if TYPE_CHECKING:
    from argus.db.models import Document

log = get_logger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; ARGUS-OSINT/0.1; +https://github.com/jaydenOoOo)"

# A summary shorter than this is effectively still a headline — worth hydrating.
MIN_USEFUL_SUMMARY = 80
_MAX_CHARS = 1800  # enough context for citation-quality analysis without blowing the prompt
_FETCH_TIMEOUT = 6.0
_MAX_WORKERS = 8

_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|nav|header|footer|form|aside)\b.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_ARTICLE = re.compile(r"<article\b.*?</article>", re.IGNORECASE | re.DOTALL)
_PARAGRAPH = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def extract_main_text(page: str, max_chars: int = _MAX_CHARS) -> str:
    """Main body text of a news page: paragraph contents, boilerplate stripped.

    Heuristic on purpose: prefer the <article> region when present, keep <p> blocks that
    look like prose (long enough, sentence-like), and cap the total. Imperfect extraction
    of real text still beats a bare headline."""
    if not page:
        return ""
    cleaned = _COMMENTS.sub(" ", _DROP_BLOCKS.sub(" ", page))
    scope = _ARTICLE.search(cleaned)
    body = scope.group(0) if scope else cleaned
    paragraphs: list[str] = []
    total = 0
    for match in _PARAGRAPH.finditer(body):
        text = _WS.sub(" ", html_lib.unescape(_TAG.sub(" ", match.group(1)))).strip()
        # Prose filter: cookie banners, bylines and nav crumbs are short or verb-less.
        if len(text) < 60 or " " not in text:
            continue
        paragraphs.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return " ".join(paragraphs)[:max_chars]


def _fetch_text(url: str) -> str:
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return extract_main_text(resp.text)
    except Exception:  # any fetch/parse failure -> keep the headline
        return ""


def needs_text(doc: "Document") -> bool:
    return bool(doc.url) and len(doc.summary or "") < MIN_USEFUL_SUMMARY


def hydrate_documents(docs: list["Document"], limit: int | None = None) -> int:
    """Fetch article text for headline-only documents (in place, parallel, best-effort).

    Sets `doc.summary` and clears `doc.embedding` so the next enrichment pass re-embeds
    over the real text (callers that run enrichment/embedding afterwards pick it up).
    Returns how many documents gained text. Never raises."""
    todo = [d for d in docs if needs_text(d)]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        return 0
    hydrated = 0
    try:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            texts = list(pool.map(lambda d: _fetch_text(d.url or ""), todo))
        for doc, text in zip(todo, texts, strict=True):
            if text:
                doc.summary = text
                doc.embedding = None  # stale: was computed over the bare headline
                hydrated += 1
    except Exception as exc:  # hydration must never break collection or a brief
        log.warning("hydration_failed", error=str(exc))
        return hydrated
    log.info("documents_hydrated", requested=len(todo), hydrated=hydrated)
    return hydrated


def reembed_documents(docs: list["Document"]) -> None:
    """Refresh embeddings for docs whose text changed (no-op without the embed model)."""
    stale = [d for d in docs if d.embedding is None and d.summary]
    if not stale:
        return
    try:
        from argus.nlp.embed import embed_texts

        vectors = embed_texts([f"{d.title}. {d.summary}" for d in stale])
        for doc, vec in zip(stale, vectors, strict=True):
            doc.embedding = [float(x) for x in vec]
    except Exception as exc:  # slim deployment / model unavailable -> BM25 still works
        log.warning("reembed_skipped", error=str(exc))


def hydration_limit() -> int:
    return get_settings().hydrate_max_per_collect
