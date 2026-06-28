from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from argus.db.models import Document, Narrative, Source
from argus.narrative.cluster import cluster_narratives
from argus.narrative.coordination import burstiness, coordination_score, low_reliability_share
from argus.narrative.run import rebuild_narratives

_T = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def test_cluster_keeps_only_min_size_clusters() -> None:
    # 3 near-identical + 1 outlier; min_size=3 -> one narrative, outlier dropped.
    emb = np.asarray([[1.0, 0.0], [0.99, 0.14], [0.98, 0.2], [0.0, 1.0]], dtype=np.float32)
    clusters = cluster_narratives(emb, threshold=0.6, min_size=3)
    assert len(clusters) == 1
    assert sorted(clusters[0]) == [0, 1, 2]


def test_burstiness_and_low_reliability() -> None:
    window = timedelta(hours=6)
    tight = [_T, _T + timedelta(hours=1), _T + timedelta(hours=2)]
    assert burstiness(tight, window) == 1.0  # all within one window
    spread = [_T, _T + timedelta(days=2), _T + timedelta(days=4)]
    assert burstiness(spread, window) < 1.0
    assert low_reliability_share(["A", "D", "F", "B"]) == 0.5


def test_coordination_dampened_by_reliable_sources() -> None:
    window = timedelta(hours=6)
    times = [_T, _T + timedelta(hours=1), _T + timedelta(hours=2)]
    # Same burst; state-affiliated push scores higher than reputable coverage.
    state = coordination_score(times, ["D", "F", "D"], window)
    reputable = coordination_score(times, ["A", "B", "B"], window)
    assert state > reputable
    assert 0.0 <= reputable <= 1.0 and 0.0 <= state <= 1.0


def test_rebuild_narratives_persists_with_coordination(session: Session) -> None:
    session.add(Source(label="rt.com", reliability="D"))
    session.add(Source(label="sputniknews.com", reliability="D"))
    session.add(Source(label="tass.com", reliability="D"))
    for i, src in enumerate(("rt.com", "sputniknews.com", "tass.com")):
        session.add(
            Document(
                doc_id=f"{src}:{i}",
                source=src,
                title="Foreign sabotage claim",
                embedding=[1.0, 0.0],
                published=_T + timedelta(hours=i),
            )
        )
    session.flush()

    n = rebuild_narratives(session, threshold=0.6, min_size=3, window=timedelta(hours=6))
    assert n == 1
    narrative = session.query(Narrative).one()
    assert narrative.doc_count == 3
    assert narrative.source_count == 3
    assert narrative.coordination is not None and narrative.coordination > 0.5  # synced + all D
