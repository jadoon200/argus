"""Unit tests for the ACH diagnostic scorer (argus.agent.ach)."""

from argus.agent.ach import neutral_matrix, score_matrix
from argus.agent.schemas import AchCell, AchMatrix, AchRow
from argus.agent.state import EvidenceItem


def _ev(doc_id: str, reliability: str) -> EvidenceItem:
    return EvidenceItem(
        doc_id=doc_id, title=doc_id, source=doc_id, reliability=reliability, credibility=None
    )


def test_score_matrix_ranks_by_least_weighted_disconfirmation() -> None:
    # E1 is a reliable B source; E2 is a low-reliability D source.
    evidence = [_ev("a", "B"), _ev("b", "D")]
    matrix = AchMatrix(
        rows=[
            AchRow(
                hypothesis="H1",
                cells=[
                    AchCell(evidence="E1", assessment="consistent"),
                    AchCell(evidence="E2", assessment="inconsistent"),
                ],
            ),
            AchRow(
                hypothesis="H2",
                cells=[
                    AchCell(evidence="E1", assessment="inconsistent"),
                    AchCell(evidence="E2", assessment="consistent"),
                ],
            ),
        ]
    )
    ranked = score_matrix(matrix, evidence)
    # ACH favours least disconfirmed: H1 is only contradicted by the weak D source (0.4),
    # H2 by the reliable B source (0.9) — so a low-reliability source can't sink H1.
    assert [s.hypothesis for s in ranked] == ["H1", "H2"]
    assert ranked[0].inconsistency == 0.4
    assert ranked[1].inconsistency == 0.9
    assert ranked[0].inconsistent == 1 and ranked[0].consistent == 1


def test_score_matrix_tolerates_label_variants_and_drops_fabricated_cells() -> None:
    evidence = [_ev("a", "B"), _ev("b", "D")]  # E1=B (0.9), E2=D (0.4)
    matrix = AchMatrix(
        rows=[
            # bare "1" must still resolve to E1's weight (0.9), not the 0.5 default.
            AchRow(hypothesis="H1", cells=[AchCell(evidence="1", assessment="inconsistent")]),
            # "E9" references evidence that doesn't exist — a fabricated cell, dropped.
            AchRow(hypothesis="H2", cells=[AchCell(evidence="E9", assessment="inconsistent")]),
        ]
    )
    ranked = score_matrix(matrix, evidence)
    by_h = {s.hypothesis: s for s in ranked}
    assert by_h["H1"].inconsistency == 0.9 and by_h["H1"].inconsistent == 1
    assert by_h["H2"].inconsistency == 0.0 and by_h["H2"].inconsistent == 0  # fabricated dropped
    assert ranked[0].hypothesis == "H2"  # nothing disconfirms it (after dropping the fake cell)


def test_neutral_matrix_has_no_signal_and_keeps_order() -> None:
    ranked = score_matrix(neutral_matrix(["X", "Y", "Z"]), [_ev("a", "B")])
    assert [s.hypothesis for s in ranked] == ["X", "Y", "Z"]  # stable, no diagnostic signal
    assert all(s.inconsistency == 0.0 for s in ranked)
