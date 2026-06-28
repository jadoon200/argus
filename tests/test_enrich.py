from datetime import UTC, datetime

import numpy as np
import pytest
from numpy.typing import NDArray
from sqlalchemy.orm import Session

from argus.db.models import Document, Entity, Event, Source
from argus.nlp import enrich as enrich_mod

_T = datetime(2026, 6, 20, tzinfo=UTC)


def _fake_embed(texts: list[str]) -> NDArray[np.float32]:
    # alpha/beta -> same vector (cluster together), gamma -> orthogonal.
    rows = [
        [1.0, 0.0] if ("alpha" in t.lower() or "beta" in t.lower()) else [0.0, 1.0] for t in texts
    ]
    return np.asarray(rows, dtype=np.float32)


def _seed(session: Session) -> None:
    for label in ("reuters.com", "bbc-world", "apnews.com"):
        session.add(Source(label=label, reliability="B"))
    session.add(
        Document(doc_id="a", source="reuters.com", title="Alpha Command statement", published=_T)
    )
    session.add(Document(doc_id="b", source="bbc-world", title="Beta Province clash", published=_T))
    session.add(Document(doc_id="c", source="apnews.com", title="Gamma Ridge update", published=_T))
    session.flush()


def test_run_embeds_extracts_clusters_and_scores(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(enrich_mod, "embed_texts", _fake_embed)
    _seed(session)

    stats = enrich_mod.run(session)
    assert stats["embedded"] == 3
    assert stats["events"] == 2
    assert stats["entity_edges"] >= 3

    a = session.get(Document, "a")
    assert a is not None
    assert a.embedding == [1.0, 0.0]
    assert a.enriched_at is not None
    assert a.credibility == 3  # a + b corroborate (2 sources)
    assert session.get(Document, "c").credibility == 4  # single source
    assert session.query(Event).count() == 2
    assert session.query(Entity).count() >= 3


def test_run_is_idempotent(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enrich_mod, "embed_texts", _fake_embed)
    _seed(session)
    enrich_mod.run(session)
    stats2 = enrich_mod.run(session)
    assert stats2["embedded"] == 0  # already-enriched docs are skipped


def test_entity_span_spans_all_mentions(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """An entity's first_seen/last_seen must bracket every mention, regardless of the
    order documents are processed in (regression: merge used to clobber first_seen)."""
    monkeypatch.setattr(enrich_mod, "embed_texts", _fake_embed)
    early = datetime(2026, 6, 1, tzinfo=UTC)
    late = datetime(2026, 6, 20, tzinfo=UTC)
    session.add(Source(label="reuters.com", reliability="B"))
    # Same entity ("Alpha Command") in an early doc and a later doc; the later doc is
    # processed second, which is exactly when the old code overwrote first_seen.
    session.add(
        Document(doc_id="early", source="reuters.com", title="Alpha Command meets", published=early)
    )
    session.add(
        Document(
            doc_id="late", source="reuters.com", title="Alpha Command meets again", published=late
        )
    )
    session.flush()

    enrich_mod.run(session)

    alpha = next(e for e in session.query(Entity).all() if e.name == "Alpha Command")
    assert alpha.mentions == 2
    # .date() keeps the assert robust to SQLite returning naive datetimes.
    assert alpha.first_seen is not None and alpha.last_seen is not None
    assert alpha.first_seen.date() == early.date()  # earliest mention, not last-processed
    assert alpha.last_seen.date() == late.date()
