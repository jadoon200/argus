"""Collect-on-demand — fetch reporting for a question at ask-time, not as a prerequisite.

Manually ingesting a topic before asking about it was scaffolding, not a design: an analyst
workbench should treat the corpus as a *cache*. When a question finds no (or thin) relevant
evidence, `generate_brief` calls `collect_for_query` inline — GDELT fetch, persist, enrich —
then retrieves again and answers. First ask on a topic pays ~20-40s of collection; later
asks hit the corpus. The same helper backs the dashboard's `POST /ingest`.

Failures degrade to 0 documents (offline GDELT must never turn a question into an error);
the caller falls through to whatever the corpus already holds.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from argus.config import get_settings
from argus.ingest.flows import persist
from argus.ingest.gdelt import fetch_gdelt_articles
from argus.logging import get_logger
from argus.nlp import enrich

log = get_logger(__name__)


def _rebuild_narratives(session: Session) -> None:
    """Refresh the narrative-watch view after new documents land, so the dashboard's
    Narratives tab populates from normal use instead of requiring `make narratives`.
    Best-effort: a narrative failure must never fail a collection."""
    try:
        from argus.narrative.run import rebuild_narratives
        from argus.nlp.disarm import DisarmMapper

        settings = get_settings()
        count = rebuild_narratives(
            session,
            settings.narrative_threshold,
            settings.narrative_min_cluster_size,
            timedelta(hours=settings.coordination_window_hours),
            mapper=DisarmMapper(),  # same encoder as enrichment — already loaded
            disarm_top_k=settings.disarm_top_k,
            disarm_threshold=settings.disarm_threshold,
        )
        log.info("narratives_refreshed", narratives=count)
    except Exception as exc:
        log.warning("narrative_refresh_failed", error=str(exc))


def collect_for_query(session: Session, query: str) -> tuple[int, int]:
    """Fetch + persist + enrich reporting on `query`. Returns (fetched, new); (0, 0) on
    upstream failure — collection is best-effort, never the reason an answer fails."""
    try:
        articles = fetch_gdelt_articles(query)
    except Exception as exc:  # GDELT down/unreachable -> answer from the existing corpus
        log.warning("collect_on_demand_failed", error=str(exc))
        return 0, 0
    if not articles:
        return 0, 0
    counts = persist(session, articles)  # upserts graded Source rows for the FK itself
    if counts["new"]:
        # GDELT articles arrive as bare headlines — fetch their body text first so the
        # embeddings, events and the analyst's evidence are computed over real content.
        from sqlalchemy import select

        from argus.db.models import Document
        from argus.nlp.fulltext import hydrate_documents, hydration_limit

        fresh = list(session.scalars(select(Document).where(Document.embedding.is_(None))))
        hydrate_documents(fresh, limit=hydration_limit())
        enrich.run(session)  # embed + entities + rebuild events for the new documents
        _rebuild_narratives(session)  # keep the narrative-watch view current too
    log.info("collected_on_demand", query=query[:80], fetched=len(articles), new=counts["new"])
    return len(articles), counts["new"]
