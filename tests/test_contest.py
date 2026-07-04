import numpy as np

from argus.nlp.contest import crosses_reliability_tiers, framing_divergence


def test_divergence_zero_for_identical_framings() -> None:
    emb = np.asarray([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    assert framing_divergence(emb) == 0.0


def test_divergence_maxed_for_orthogonal_framings() -> None:
    emb = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)  # cosine 0 -> divergence 1
    assert framing_divergence(emb) == 1.0


def test_divergence_takes_the_most_divergent_pair() -> None:
    # two aligned framings + one at 0.6 cosine -> divergence 1 - 0.6 = 0.4
    emb = np.asarray([[1.0, 0.0], [1.0, 0.0], [0.6, 0.8]], dtype=np.float32)
    assert abs(framing_divergence(emb) - 0.4) < 1e-6


def test_single_doc_event_is_never_contested() -> None:
    assert framing_divergence(np.asarray([[1.0, 0.0]], dtype=np.float32)) == 0.0


def test_crosses_reliability_tiers() -> None:
    assert crosses_reliability_tiers(["B", "D"]) is True  # wire vs state-affiliated
    assert crosses_reliability_tiers(["A", "B", "C"]) is False  # all high tier
    assert crosses_reliability_tiers(["D", "F"]) is False  # all low tier
