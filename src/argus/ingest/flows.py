"""Prefect ingestion flow — collect open-source reporting on a topic into the corpus.

    python -m argus.ingest.flows "South China Sea"

Pulls GDELT articles for the query plus the curated RSS feeds, ensures a Source row
(with its Admiralty grade) exists for every provenance label, and inserts the *new*
documents — existing ones are left untouched so a re-run never clobbers enrichment.
"""

import sys

from prefect import flow, task

from argus.db.base import session_scope
from argus.db.models import Document
from argus.ingest.gdelt import fetch_gdelt_articles

# Prefect-free persistence lives in its own module so the slim API path can import it without
# pulling Prefect; re-exported here for the CLI flow and existing callers.
from argus.ingest.persist import ensure_sources, persist
from argus.ingest.rss import fetch_rss_documents
from argus.logging import configure_logging, get_logger

log = get_logger(__name__)

__all__ = ["collect", "ensure_sources", "ingest", "persist"]


@task
def collect(query: str) -> list[Document]:
    docs = fetch_gdelt_articles(query)
    docs.extend(fetch_rss_documents())
    return docs


@flow(name="argus-ingest")
def ingest(query: str) -> dict[str, int]:
    docs = collect(query)
    with session_scope() as session:
        stats = persist(session, docs)
    log.info("ingest_complete", query=query, **stats)
    return stats


if __name__ == "__main__":
    configure_logging()
    topic = " ".join(sys.argv[1:]).strip() or "Singapore security"
    ingest(topic)
