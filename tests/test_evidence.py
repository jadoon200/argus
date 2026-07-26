from argus.agent.analyst import generate_brief
from argus.agent.state import EvidenceItem, deduplicate_evidence


def _item(
    doc_id: str,
    *,
    title: str = "AIS spoofing - MMSI 563000029",
    source: str = "ocean-geoint",
    published: str | None = "2023-01-01T00:50:00",
    summary: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(doc_id, title, source, "B", 2, summary, published)


def test_same_source_near_duplicate_keeps_richer_representative() -> None:
    sparse = _item("spoof-1", summary="Impossible jump.")
    rich = _item(
        "spoof-2",
        published="2023-01-01T00:55:00",
        summary="Impossible jump in the Singapore Strait with zone context.",
    )
    later_episode = _item(
        "spoof-3",
        published="2023-01-01T02:00:00",
        summary="A separate impossible jump.",
    )

    result = deduplicate_evidence([sparse, rich, later_episode])

    assert [item.doc_id for item in result] == ["spoof-2", "spoof-3"]


def test_corroborating_sources_and_distinct_signals_are_not_collapsed() -> None:
    original = _item("ocean-1")
    other_source = _item("news-1", source="reuters.com")
    other_signal = _item("anomaly-1", title="Trajectory anomaly - MMSI 563000029")

    assert deduplicate_evidence([original, other_source, other_signal]) == [
        original,
        other_source,
        other_signal,
    ]


def test_missing_or_invalid_timestamps_only_deduplicate_exact_ids() -> None:
    first = _item("one", published=None)
    second = _item("two", published="not-a-date")

    assert deduplicate_evidence([first, first, second]) == [first, second]


def test_exact_duplicate_id_keeps_richer_representative() -> None:
    sparse = _item("same", published=None, summary="Short.")
    rich = _item("same", published=None, summary="Richer source context for the same item.")

    assert deduplicate_evidence([sparse, rich]) == [rich]


def test_explicit_evidence_is_deduplicated_at_the_synthesis_boundary() -> None:
    sparse = _item("spoof-1", summary="Impossible jump.")
    rich = _item(
        "spoof-2",
        published="2023-01-01T00:55:00",
        summary="Impossible jump in the Singapore Strait with zone context.",
    )

    result = generate_brief(
        "Assess AIS spoofing near Singapore",
        evidence=[sparse, rich],
        backend=None,
        persist=False,
    )

    assert result.evidence == [rich]
    assert result.citations == [rich.doc_id]
