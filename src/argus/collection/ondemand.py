"""Collect-on-demand — fetch reporting for a question at ask-time, not as a prerequisite.

Manually ingesting a topic before asking about it was scaffolding, not a design: an analyst
workbench should treat the corpus as a *cache*. When a question finds no (or thin) relevant
evidence, `generate_brief` calls `collect_for_query` inline — GDELT fetch, persist, enrich —
then retrieves again and answers. First ask on a topic pays ~20-40s of collection; later
asks hit the corpus. The same helper backs the dashboard's `POST /ingest`.

Failures degrade to 0 documents (offline GDELT must never turn a question into an error);
the caller falls through to whatever the corpus already holds.
"""

from sqlalchemy.orm import Session

from argus.ingest.flows import persist
from argus.ingest.gdelt import fetch_gdelt_articles
from argus.logging import get_logger
from argus.nlp import enrich

log = get_logger(__name__)


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
        enrich.run(session)  # embed + entities + rebuild events for the new documents
    log.info("collected_on_demand", query=query[:80], fetched=len(articles), new=counts["new"])
    return len(articles), counts["new"]
