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


def test_neutral_matrix_has_no_signal_and_keeps_order() -> None:
    ranked = score_matrix(neutral_matrix(["X", "Y", "Z"]), [_ev("a", "B")])
    assert [s.hypothesis for s in ranked] == ["X", "Y", "Z"]  # stable, no diagnostic signal
    assert all(s.inconsistency == 0.0 for s in ranked)
