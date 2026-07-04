"""Closing-the-loop collection: brief -> gaps -> queries -> ingest -> re-brief.

    python -m argus.collection.loop "What is driving tensions in the South China Sea?"

An analyst brief ends with its intelligence gaps. This runs an initial brief, turns those
gaps into targeted GDELT queries, ingests + enriches the new reporting, and re-briefs on
the expanded corpus — so the agent tasks its own collection instead of stopping at "we
don't know." Free/local end to end.
"""

import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

from argus.agent.analyst import generate_brief, render
from argus.agent.llm import resolve_backend
from argus.agent.state import BriefResult
from argus.collection.tasking import derive_queries
from argus.db.base import session_scope
from argus.ingest.flows import persist
from argus.ingest.gdelt import fetch_gdelt_articles
from argus.logging import configure_logging, get_logger
from argus.nlp import enrich

log = get_logger(__name__)


@dataclass
class LoopResult:
    query: str
    tasked_queries: list[str]
    ingested: int
    brief_before: BriefResult
    brief_after: BriefResult


def run_collection_loop(query: str, session: Session, max_queries: int = 4) -> LoopResult:
    backend = resolve_backend()
    before = generate_brief(query, session=session, backend=backend, persist=False)

    tasked = derive_queries(before, backend, max_queries)
    ingested = 0
    for tasked_query in tasked:
        ingested += persist(session, fetch_gdelt_articles(tasked_query))["new"]
    if ingested:
        enrich.run(session)  # embed the new docs + re-cluster events before re-briefing

    after = generate_brief(query, session=session, backend=backend, persist=False)
    log.info("collection_loop", tasked=len(tasked), ingested=ingested)
    return LoopResult(query, tasked, ingested, before, after)


def main() -> None:
    configure_logging()
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('usage: python -m argus.collection.loop "<question>"')
        raise SystemExit(2)
    with session_scope() as session:
        result = run_collection_loop(question, session)
    print("=== TASKED COLLECTION (from the first brief's gaps) ===")
    for q in result.tasked_queries:
        print(f"  • {q}")
    print(f"\ningested {result.ingested} new documents\n")
    print("=== RE-BRIEF (expanded corpus) ===")
    print(render(result.brief_after))


if __name__ == "__main__":
    main()
