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

# Topically-empty words — analytic framing, generic conflict vocabulary, and time refs. A
# query must not look "relevant" to a document just because they share one of these: "assess
# tensions between US and Iran" should NOT match South-China-Sea reporting merely via the word
# "tensions". Relevance is judged on the SUBJECT tokens left after these are removed. (Kept out
# of _STOPWORDS because the panel prompts still want them; only the relevance gate strips them.)
_GENERIC = frozenset(
    [
        "assess",
        "assessment",
        "analyse",
        "analyze",
        "analysis",
        "evaluate",
        "review",
        "update",
        "latest",
        "current",
        "currently",
        "now",
        "today",
        "recent",
        "recently",
        "situation",
        "status",
        "overview",
        "summary",
        "brief",
        "briefing",
        "explain",
        "happening",
        "going",
        "driving",
        "behind",
        "tension",
        "tensions",
        "crisis",
        "crises",
        "conflict",
        "dispute",
        "standoff",
        "escalation",
        "unrest",
        "developments",
        "news",
        "report",
        "reporting",
        "story",
        "wave",
        "between",
        "around",
        "amid",
    ]
)


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
        "- Fuse every source domain - a deterministic supervisor routes the question to "
        "OSINT plus the relevant Sky/HORUS, Ocean/PHAROS, and Cyber/SENTINEL workers; "
        "each returns citable, source-rated evidence before one central synthesis.\n\n"
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


def no_reporting_brief(
    query: str, corpus_size: int, collection_enabled: bool = True
) -> BriefResult:
    """Instant answer when the corpus holds nothing relevant: say so and guide the analyst.

    `collection_enabled` mirrors `ARGUS_AUTO_COLLECT`: when on (the full app), guide the user to
    collect the topic; when off (e.g. the free hosted demo, which can't run the embedding model
    to ingest), be honest that this deployment only answers over its fixed corpus. The gaps text
    embeds the raw query so the collection loop's fallback derivation can task ingestion."""
    if corpus_size == 0:
        reason = "The corpus is empty - no open-source reporting has been ingested yet."
    else:
        reason = f"None of the {corpus_size} ingested documents appear relevant to this question."
    if collection_enabled:
        how = (
            "An assessment needs evidence; rather than speculate, collect first:\n\n"
            "- Dashboard: Collection view -> type this topic into the ingest box\n"
            f'- CLI: make ingest Q="{query}" then make enrich\n\n'
            "Then ask again - every judgment will carry citations to the ingested reporting."
        )
    else:
        how = (
            "This deployment analyses a fixed sample corpus and does not collect new topics "
            "live, so it can only answer questions about reporting already ingested - open the "
            "Collection view to see what's covered, or try one of the example questions. To "
            "analyse any topic with live collection, run ARGUS locally (ARGUS_AUTO_COLLECT)."
        )
    body = f"No relevant reporting available for: {query}\n\n{reason} {how}"
    return BriefResult(
        query=query,
        body=body,
        confidence=None,
        gaps=f"No ingested reporting relevant to: {query}. Collection required.",
        backend="triage",
    )


def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _STOPWORDS}


def _is_generic(token: str) -> bool:
    # Plural-tolerant: the registry lists mostly singular forms ("update"), but users type
    # both ("any updates?") — a trailing-s variant of a generic word is still generic.
    return token in _GENERIC or (token.endswith("s") and token[:-1] in _GENERIC)


def subject_tokens(text: str) -> set[str]:
    """Content-bearing subject tokens used by deterministic relevance and lane routing.

    Keeping this extraction public gives the fusion supervisor the exact same definition of
    "subject-less" as query triage, so conversational follow-ups consistently fan out rather
    than being mistaken for an unrelated query.
    """
    return {token for token in _content_tokens(text) if not _is_generic(token)}


def relevant_count(query: str, evidence: list[EvidenceItem]) -> int:
    """How many evidence items share a SUBJECT token with the query — the thin-coverage
    signal that triggers collect-on-demand (fewer relevant docs than the configured floor).

    Matches on the query's subject tokens (content words minus generic framing/time words), so
    a document isn't counted relevant just because it shares a word like "tensions" or "recent".
    """
    q_tokens = subject_tokens(query)
    if not q_tokens:
        # No subject to match on (e.g. "any updates?") — relevance is unknowable, not zero.
        # Count everything so a conversational follow-up neither trips the no-reporting gate
        # nor tasks collection on a subject-less query; empty evidence still counts 0.
        return len(evidence)
    return sum(1 for e in evidence if q_tokens & _content_tokens(f"{e.title} {e.summary or ''}"))


def has_relevant_evidence(query: str, evidence: list[EvidenceItem]) -> bool:
    """Cheap relevance gate: does ANY evidence item share a content token with the query?

    Hybrid retrieval always returns the least-irrelevant top-k from whatever the corpus
    holds; when the corpus has nothing on the topic, that evidence is noise and the panel
    would deliberate to a predetermined 'no evidence' - detect it deterministically instead.
    Conservative on purpose: one shared content token anywhere keeps the evidence."""
    return relevant_count(query, evidence) > 0
