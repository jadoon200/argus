from typing import Any

import pytest
from sqlalchemy.orm import Session

from argus.agent.analyst import generate_brief
from argus.agent.state import EvidenceItem
from argus.agent.triage import (
    capabilities_brief,
    has_relevant_evidence,
    is_meta_query,
    no_reporting_brief,
    relevant_count,
)
from argus.db.models import Document, Source


@pytest.fixture(autouse=True)
def _no_network_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collect-on-demand must never hit GDELT from tests — default it to 'found nothing'.
    Tests that exercise collection override this with their own fake."""
    monkeypatch.setattr("argus.agent.analyst.collect_for_query", lambda s, q: (0, 0))


class ExplodingBackend:
    """A backend that must never be reached — triage answers before any LLM call."""

    name = "boom"

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        raise AssertionError("triage should have answered before any LLM call")


def _ev(title: str, summary: str) -> EvidenceItem:
    return EvidenceItem(
        doc_id="reuters.com:1",
        title=title,
        source="reuters.com",
        reliability="B",
        credibility=2,
        summary=summary,
    )


def test_meta_queries_detected() -> None:
    for q in ("what can u do", "What can you do?", "hi", "Help", "who are you", "test"):
        assert is_meta_query(q), q


def test_analytic_queries_are_not_meta() -> None:
    for q in (
        "What is happening at the disputed reef?",
        "what can China do about the blockade",  # starts meta-ish but is analytic
        "help me understand the coup in the capital",
        "Was the outage caused by sabotage?",
    ):
        assert not is_meta_query(q), q


def test_relevance_gate() -> None:
    reef = [_ev("Coast guard standoff at reef", "vessels massed near the disputed reef")]
    assert has_relevant_evidence("What is happening at the disputed reef?", reef)
    assert not has_relevant_evidence("quantum banking collapse in the metaverse", reef)
    # Subject-less queries can't be assessed for relevance — pass evidence through rather
    # than falsely report "no relevant reporting" on a conversational follow-up (true meta
    # queries like "what can u do" never reach this gate; is_meta_query catches them first).
    assert has_relevant_evidence("Any updates?", reef)
    assert has_relevant_evidence("what can u do", reef)
    assert not has_relevant_evidence("anything at all", [])  # no evidence is still a miss


def test_meta_query_short_circuits_before_llm_and_retrieval() -> None:
    # No session, no evidence — triage must answer before either is needed.
    result = generate_brief(
        "what can u do", evidence=None, session=None, backend=ExplodingBackend()
    )  # type: ignore[arg-type]
    assert result.backend == "triage"
    assert "ARGUS" in result.body and "analyst workbench" in result.body
    assert "**" not in result.body  # plain text — the chat UI does not render markdown


def test_empty_corpus_short_circuits_the_panel(session: Session) -> None:
    result = generate_brief(
        "What is driving tensions in the South China Sea?",
        session=session,
        backend=ExplodingBackend(),
    )
    assert result.backend == "triage"
    assert "corpus is empty" in result.body
    assert 'make ingest Q="What is driving tensions in the South China Sea?"' in result.body
    # The gaps text carries the query so the collection loop can derive search queries.
    assert result.gaps is not None and "South China Sea" in result.gaps


def test_irrelevant_corpus_short_circuits_the_panel(session: Session) -> None:
    session.add(Source(label="bbc-world", reliability="B"))
    session.add(
        Document(
            doc_id="bbc-world:1",
            source="bbc-world",
            title="Heatwave breaks temperature records",
            summary="A severe heatwave set records across Europe.",
        )
    )
    session.flush()
    result = generate_brief(
        "Who fired first in the border clash?", session=session, backend=ExplodingBackend()
    )
    assert result.backend == "triage"
    assert "appear relevant" in result.body  # names the mismatch, not an empty corpus


def test_relevant_corpus_proceeds_to_a_real_brief(session: Session) -> None:
    session.add(Source(label="reuters.com", reliability="B"))
    session.add(
        Document(
            doc_id="reuters.com:1",
            source="reuters.com",
            title="Coast guard standoff at disputed reef",
            summary="Vessels massed near the disputed reef on Tuesday.",
        )
    )
    session.flush()
    # backend=None -> deterministic digest; the point is triage does NOT intercept.
    result = generate_brief(
        "What is happening at the disputed reef?", session=session, backend=None, persist=False
    )
    assert result.backend == "template"
    assert result.citations == ["reuters.com:1"]


def test_canned_briefs_are_not_assessments() -> None:
    assert capabilities_brief("hi").confidence is None
    assert no_reporting_brief("q", 0).confidence is None
    assert no_reporting_brief("q", 7).body.count("7") >= 1  # names the corpus size


def test_relevant_count() -> None:
    reef = [_ev("Coast guard standoff at reef", "vessels massed near the disputed reef")]
    assert relevant_count("What is happening at the disputed reef?", reef) == 1
    assert relevant_count("quantum banking collapse", reef) == 0


def test_collect_on_demand_fills_an_empty_corpus(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty corpus; the collector "fetches" a relevant doc — the question is then answered
    # from it instead of returning the no-reporting card.
    def fake_collect(db: Session, query: str) -> tuple[int, int]:
        db.add(Source(label="reuters.com", reliability="B"))
        db.add(
            Document(
                doc_id="reuters.com:9",
                source="reuters.com",
                title="Coast guard standoff at disputed reef",
                summary="Vessels massed near the disputed reef.",
            )
        )
        db.flush()
        return 3, 1

    monkeypatch.setattr("argus.agent.analyst.collect_for_query", fake_collect)
    result = generate_brief(
        "What is happening at the disputed reef?", session=session, backend=None, persist=False
    )
    assert result.backend == "template"  # answered (digest), not triaged
    assert result.auto_collected == 1  # transparency: how many docs were fetched
    assert result.citations == ["reuters.com:9"]


def test_collect_on_demand_failure_still_triages(session: Session) -> None:
    # Autouse fixture makes collection find nothing -> honest no-reporting card, no crash.
    result = generate_brief("obscure topic nowhere in news", session=session, backend=None)
    assert result.backend == "triage"
    assert result.auto_collected == 0
