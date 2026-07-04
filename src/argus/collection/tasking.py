"""Collection tasking — turn a brief's intelligence gaps into the next search queries.

A brief already ends with what it does NOT know (intelligence gaps + a collection
requirement). This closes the loop: those gaps become concrete open-source search queries
for the next ingest, so the system tasks its own collection. Free/local via the same
backend, with a deterministic fallback (extract the named entities from the gaps text) so
it works with no LLM.
"""

import re

from pydantic import BaseModel, Field

from argus.agent.llm import LLMBackend
from argus.agent.state import BriefResult
from argus.agent.structured import complete_model

_TASKING_SYSTEM = """You are an intelligence collection manager. Given a brief's QUESTION,
its INTELLIGENCE GAPS, and any COLLECTION REQUIREMENT, produce 2-4 concrete open-source
search queries that would help FILL those gaps. Each query is a short keyword phrase for a
news/OSINT search engine (actors, places, events) — no boolean operators, no punctuation.
Target the gaps specifically; do not just restate the original question."""

# Capitalised multi-word spans in the gaps text — a dependency-free stand-in for the
# entities a collector would chase when no model is available.
_CAP_SPAN = re.compile(r"\b([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)+)\b")


class CollectionTasking(BaseModel):
    queries: list[str] = Field(default_factory=list)


def _fallback_queries(gaps: str, max_queries: int) -> list[str]:
    spans = list(dict.fromkeys(_CAP_SPAN.findall(gaps)))  # dedupe, preserve order
    return spans[:max_queries]


def derive_queries(
    brief: BriefResult, backend: LLMBackend | None, max_queries: int = 4
) -> list[str]:
    """Search queries that would fill the brief's intelligence gaps ([] if there are none)."""
    gaps = (brief.gaps or "").strip()
    requirement = (brief.alternatives or "").strip()  # collection requirement is folded here
    if not gaps and not requirement:
        return []
    if backend is not None:
        user = (
            f"QUESTION: {brief.query}\n\nINTELLIGENCE GAPS: {gaps or '(none stated)'}\n\n"
            f"COLLECTION REQUIREMENT: {requirement or '(none stated)'}\n\nProduce the queries."
        )
        tasking = complete_model(backend, _TASKING_SYSTEM, user, CollectionTasking, temperature=0.3)
        if tasking is not None and tasking.queries:
            queries = [q.strip() for q in tasking.queries if q.strip()]
            if queries:
                return queries[:max_queries]
    return _fallback_queries(gaps, max_queries)
