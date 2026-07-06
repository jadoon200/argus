"""Query triage — answer instantly what never needed a deliberation.

The multi-agent panel is minutes of local-LLM inference. Two classes of query must never
reach it:

- **Meta/conversational** ("what can you do", "hi", "help") — the honest answer is a canned
  capabilities response, in milliseconds, not an ACH deliberation about the question itself.
- **No relevant reporting** — when the corpus is empty (or shares nothing with the query),
  the deliberation's conclusion is predetermined ("no evidence"); running the panel anyway
  burns minutes to say what a deterministic check knows instantly. The right product is a
  fast "no reporting — here is what to collect" response whose gaps text feeds the
  collection loop (`derive_queries` extracts its capitalized spans as search queries).

Both paths are deterministic (no LLM), and neither is persisted — they are guidance, not
intelligence products.
"""

import re

from argus.agent.state import BriefResult, EvidenceItem

# Meta/conversational openers a chat UI attracts. Deliberately narrow: a real analytic
# question ("what is happening at the reef?") must never match.
_META_RE = re.compile(
    r"^\s*(?:"
    r"hi|hello|hey|yo|sup|thanks?|thank you|ok(?:ay)?|help"
    r"|what can (?:you|u) do|what do (?:you|u) do|what are (?:you|u)|who are (?:you|u)"
    r"|what is this|what'?s this|how do(?:es)? (?:you|u|this|it) work|test(?:ing)?"
    r")\s*[?!.]*\s*$",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "can",
        "you",
        "what",
        "who",
        "how",
        "did",
        "was",
        "were",
        "are",
        "for",
        "with",
        "from",
        "about",
        "has",
        "have",
        "this",
        "that",
        "will",
        "its",
        "not",
        "why",
        "when",
        "where",
        "does",
        "into",
        "over",
        "under",
        "near",
        "been",
        "being",
        "them",
        "they",
        "their",
        "there",
        "his",
        "her",
        "him",
        "she",
        "our",
        "your",
        "out",
        "any",
        "all",
        "more",
        "most",
        "some",
        "such",
        "off",
        "per",
        "via",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]{3,}")


def is_meta_query(query: str) -> bool:
    """True for conversational/meta questions that need no evidence or deliberation."""
    return bool(_META_RE.match(query or ""))


def capabilities_brief(query: str) -> BriefResult:
    """Instant, canned answer to 'what can you do' — no LLM, no retrieval."""
    body = (
        "ARGUS is an all-source intelligence analyst workbench. Ask it an analytic "
        "question about world events and it will:\n\n"
        "- Collect open-source reporting (GDELT global news + curated wire/agency RSS) "
        "on your topics - use the Collection view's ingest box.\n"
        "- Rate every source on the NATO Admiralty scale (reliability A-F x credibility "
        "1-6) and deduplicate reporting into events.\n"
        "- Brief you two ways: Quick (one model pass, chat-speed) or Deliberate (a "
        "multi-agent panel - hypotheses, ACH scoring, analyst vs red-team, adjudicator - "
        "for the deep assessment). Every judgment cites real ingested documents, with "
        "calibrated confidence, key assumptions, indicators & warnings, and gaps.\n"
        "- Watch narratives - clusters coordinated messaging, flags contested events, and "
        "tags influence-operations techniques (DISARM framework).\n"
        "- Fuse the cyber picture - joins SENTINEL cyber campaigns (ATT&CK) into a brief "
        "as citable evidence, with threat-actor -> nation attribution.\n\n"
        "Try: ingest a topic in the Collection view, then ask something like "
        '"What is driving tensions in the South China Sea?"'
    )
    return BriefResult(
        query=query,
        body=body,
        confidence=None,
        gaps=None,
        backend="triage",
    )


def no_reporting_brief(query: str, corpus_size: int) -> BriefResult:
    """Instant answer when the corpus holds nothing relevant: say so and task collection.

    The gaps text embeds the raw query, so the collection loop's fallback query derivation
    (capitalized spans) can turn this straight into targeted ingestion."""
    if corpus_size == 0:
        reason = "The corpus is empty - no open-source reporting has been ingested yet."
    else:
        reason = f"None of the {corpus_size} ingested documents appear relevant to this question."
    body = (
        f"No relevant reporting available for: {query}\n\n"
        f"{reason} An assessment needs evidence; rather than speculate, collect first:\n\n"
        "- Dashboard: Collection view -> type this topic into the ingest box\n"
        f'- CLI: make ingest Q="{query}" then make enrich\n\n'
        "Then ask again - every judgment will carry citations to the ingested reporting."
    )
    return BriefResult(
        query=query,
        body=body,
        confidence=None,
        gaps=f"No ingested reporting relevant to: {query}. Collection required.",
        backend="triage",
    )


def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS}


def relevant_count(query: str, evidence: list[EvidenceItem]) -> int:
    """How many evidence items share a content token with the query — the thin-coverage
    signal that triggers collect-on-demand (fewer relevant docs than the configured floor)."""
    q_tokens = _content_tokens(query)
    if not q_tokens:
        return 0  # a query with no content words can't be assessed against evidence
    return sum(1 for e in evidence if q_tokens & _content_tokens(f"{e.title} {e.summary or ''}"))


def has_relevant_evidence(query: str, evidence: list[EvidenceItem]) -> bool:
    """Cheap relevance gate: does ANY evidence item share a content token with the query?

    Hybrid retrieval always returns the least-irrelevant top-k from whatever the corpus
    holds; when the corpus has nothing on the topic, that evidence is noise and the panel
    would deliberate to a predetermined 'no evidence' - detect it deterministically instead.
    Conservative on purpose: one shared content token anywhere keeps the evidence."""
    return relevant_count(query, evidence) > 0
