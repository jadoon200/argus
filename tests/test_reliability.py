from argus.nlp.reliability import (
    admiralty_code,
    credibility_from_corroboration,
    credibility_label,
    reliability_label,
)


def test_credibility_from_corroboration_grades() -> None:
    assert credibility_from_corroboration(5) == 1
    assert credibility_from_corroboration(4) == 1
    assert credibility_from_corroboration(3) == 2
    assert credibility_from_corroboration(2) == 3
    assert credibility_from_corroboration(1) == 4
    assert credibility_from_corroboration(0) == 6  # un-enriched / no corroboration


def test_labels() -> None:
    assert reliability_label("B") == "usually reliable"
    assert reliability_label("z") == "reliability cannot be judged"  # unknown -> F label
    assert credibility_label(1) == "confirmed by other sources"
    assert credibility_label(None) == "cannot be judged"


def test_admiralty_code() -> None:
    assert admiralty_code("B", 2) == "B2"
    assert admiralty_code("", None) == "F6"
    assert admiralty_code("d", 4) == "D4"
