from datetime import UTC, datetime

from sqlalchemy.orm import Session

from argus.agent.analyst import gather_evidence, generate_brief
from argus.db.models import Brief, Document, Source

_T = datetime(2026, 6, 20, tzinfo=UTC)


def _seed(session: Session) -> None:
    session.add(Source(label="reuters.com", name="Reuters", reliability="B"))
    session.add(Source(label="rt.com", name="RT", reliability="D"))
    session.add(
        Document(
            doc_id="reuters.com:1",
            source="reuters.com",
            title="Coast guard standoff near disputed reef",
            summary="Vessels confronted over the reef.",
            credibility=3,
            published=_T,
        )
    )
    session.add(
        Document(
            doc_id="rt.com:9",
            source="rt.com",
            title="Markets steady amid earnings",
            summary="Unrelated business news.",
            credibility=4,
            published=_T,
        )
    )
    session.flush()


def test_gather_evidence_ranks_and_rates(session: Session) -> None:
    _seed(session)
    items = gather_evidence(session, "standoff at the disputed reef", k=2)
    assert items[0].doc_id == "reuters.com:1"  # lexically the relevant one
    assert items[0].reliability == "B"  # joined from Source
    assert items[0].rating() == "B3"


def test_gather_evidence_caps_per_source(session: Session) -> None:
    """One prolific outlet must not dominate the evidence: the per-source cap holds and a
    second source still makes the cut even when it ranks below the dominant one."""
    session.add(Source(label="dominant.com", name="Dominant", reliability="C"))
    session.add(Source(label="other.com", name="Other", reliability="B"))
    for i in range(4):
        session.add(
            Document(
                doc_id=f"dominant.com:{i}",
                source="dominant.com",
                title="reef standoff coast guard",
                summary="standoff at the reef",
                published=_T,
            )
        )
    session.add(
        Document(
            doc_id="other.com:1",
            source="other.com",
            title="reef standoff coast guard vessels",
            summary="standoff at the reef",
            published=_T,
        )
    )
    session.flush()

    items = gather_evidence(session, "reef standoff", k=3, max_per_source=2)
    sources = [it.source for it in items]
    assert len(items) == 3
    assert sources.count("dominant.com") <= 2  # capped
    assert "other.com" in sources  # diversity reaches past the dominant source


def test_generate_brief_template_path_persists(session: Session) -> None:
    _seed(session)
    # backend=None forces the deterministic digest (no LLM, no network).
    result = generate_brief("standoff at the disputed reef", session=session, backend=None)
    session.commit()

    assert result.backend == "template"
    assert "reuters.com:1" in result.citations
    assert session.query(Brief).count() == 1
    stored = session.query(Brief).one()
    assert stored.backend == "template"
    assert stored.query == "standoff at the disputed reef"
