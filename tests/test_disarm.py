from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from argus.db.models import Document, Narrative, Source
from argus.narrative.run import rebuild_narratives
from argus.nlp.disarm import (
    CATALOG_BY_ID,
    DISARM_TECHNIQUES,
    PHASES,
    DisarmMapper,
    DisarmTechnique,
    lexical_match,
)

_T = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def test_catalog_integrity() -> None:
    ids = [t.technique_id for t in DISARM_TECHNIQUES]
    assert len(ids) == len(set(ids))  # unique technique ids
    assert CATALOG_BY_ID["T0086.002"].name == "Develop AI-Generated Images (Deepfakes)"
    for t in DISARM_TECHNIQUES:
        assert t.phase in PHASES  # every technique in a real DISARM phase
        assert t.technique_id.startswith("T0")


class _KeywordEmbedder:
    """Deterministic bag-of-words embedder over a fixed vocabulary — lets the cosine mapper
    be tested with no sentence-transformers model."""

    def __init__(self, vocab: list[str]) -> None:
        self._vocab = vocab

    def __call__(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            low = text.lower()
            rows.append([float(low.count(term)) for term in self._vocab])
        return np.asarray(rows, dtype=np.float32)


def test_mapper_retrieves_nearest_technique() -> None:
    # Two-technique catalog on orthogonal vocab; deepfake text must map to the deepfake one.
    catalog = [
        DisarmTechnique("T0086.002", "Deepfake images", "Prepare", "generative deepfake image"),
        DisarmTechnique("T0057", "Organise events", "Execute", "stage rally protest event"),
    ]
    embed = _KeywordEmbedder(["deepfake", "image", "rally", "protest"])
    mapper = DisarmMapper(techniques=catalog, embed=embed)

    matches = mapper.map_text("A fabricated deepfake image spread online", top_k=2, threshold=0.1)
    assert matches
    assert matches[0].technique_id == "T0086.002"
    assert matches[0].score > matches[-1].score or len(matches) == 1


def test_mapper_threshold_filters_and_dim_mismatch_is_safe() -> None:
    catalog = [DisarmTechnique("T0057", "Organise events", "Execute", "stage rally protest event")]
    embed = _KeywordEmbedder(["rally", "protest"])
    mapper = DisarmMapper(techniques=catalog, embed=embed)

    # Text with no overlap -> zero vector -> nothing above threshold.
    assert mapper.map_text("central bank interest rate decision", top_k=3, threshold=0.1) == []
    # A wrong-dimension centroid must not raise — it returns no tags.
    assert mapper.map_vector(np.ones(7, dtype=np.float32), threshold=0.1) == []


def test_lexical_fallback_ranks_by_overlap() -> None:
    matches = lexical_match("state outlet floods the space with conspiracy narratives", top_k=3)
    ids = {m.technique_id for m in matches}
    # Conspiracy-theory and/or information-pollution techniques should surface on these words.
    assert ids & {"T0022", "T0019", "T0002", "T0049"}


def test_rebuild_tags_narratives_with_disarm(session: Session) -> None:
    # Fake 2-D doc embeddings; a matching 2-D keyword-style mapper so dims align without a model.
    catalog = [
        DisarmTechnique("T0022", "Conspiracy narratives", "Execute", "conspiracy"),
        DisarmTechnique("T0057", "Organise events", "Execute", "rally"),
    ]

    def embed(texts: list[str]) -> np.ndarray:
        # "conspiracy" -> [1,0], "rally" -> [0,1]; narrative docs embed as [1,0].
        return np.asarray(
            [[1.0, 0.0] if "conspiracy" in t.lower() else [0.0, 1.0] for t in texts],
            dtype=np.float32,
        )

    mapper = DisarmMapper(techniques=catalog, embed=embed)
    for i in range(3):
        session.add(Source(label=f"src{i}", reliability="D"))
        session.add(
            Document(
                doc_id=f"src{i}:{i}",
                source=f"src{i}",
                title="conspiracy claim",
                embedding=[1.0, 0.0],
                published=_T + timedelta(hours=i),
            )
        )
    session.flush()

    n = rebuild_narratives(
        session,
        threshold=0.6,
        min_size=3,
        window=timedelta(hours=6),
        mapper=mapper,
        disarm_threshold=0.5,
    )
    assert n == 1
    narrative = session.query(Narrative).one()
    assert narrative.disarm  # tagged
    assert narrative.disarm[0]["technique_id"] == "T0022"


def test_rebuild_without_mapper_leaves_disarm_null(session: Session) -> None:
    session.add(Source(label="rt.com", reliability="D"))
    for i in range(3):
        session.add(
            Document(
                doc_id=f"rt.com:{i}",
                source="rt.com",
                title="claim",
                embedding=[1.0, 0.0],
                published=_T + timedelta(hours=i),
            )
        )
    session.flush()
    rebuild_narratives(session, threshold=0.6, min_size=3, window=timedelta(hours=6))  # no mapper
    assert session.query(Narrative).one().disarm is None
