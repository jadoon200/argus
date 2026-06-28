"""Analysis of Competing Hypotheses — the diagnostic scorer.

ACH's central move is *disconfirmation*: the strongest hypothesis is the one left with
the least credible evidence *against* it, not the one with the most evidence *for* it
(confirming evidence is often non-diagnostic — consistent with several hypotheses at
once). So we score each hypothesis by its reliability-weighted *inconsistent* evidence
and rank ascending. A pure function over the matrix the agent produces — testable, and
identical whether the matrix came from an LLM or the deterministic fallback.
"""

from argus.agent.schemas import AchMatrix
from argus.agent.state import EvidenceItem, HypothesisScore, evidence_labels

# An inconsistency flagged by a reliable source is far more diagnostic than one from a
# state-affiliated or unjudgeable outlet — weight disconfirmation by Admiralty reliability
# so a low-reliability source can't, on its own, knock out a hypothesis.
_RELIABILITY_WEIGHT: dict[str, float] = {
    "A": 1.0,
    "B": 0.9,
    "C": 0.7,
    "D": 0.4,
    "E": 0.3,
    "F": 0.5,  # "cannot be judged" — mid, neither trusted nor dismissed
}


def _weight(reliability: str) -> float:
    return _RELIABILITY_WEIGHT.get((reliability or "F").upper(), 0.5)


def score_matrix(matrix: AchMatrix, evidence: list[EvidenceItem]) -> list[HypothesisScore]:
    """Rank hypotheses by least reliability-weighted disconfirming evidence (ACH).

    Ties (e.g. the all-neutral deterministic fallback) preserve the input hypothesis
    order, so the ranking is stable and honest when no diagnostic signal exists.
    """
    weights = {label: _weight(item.reliability) for label, item in _label_reliability(evidence)}
    scores: list[HypothesisScore] = []
    for row in matrix.rows:
        inconsistency = 0.0
        consistent = inconsistent = 0
        for cell in row.cells:
            if cell.assessment == "inconsistent":
                inconsistency += weights.get(cell.evidence.strip(), 0.5)
                inconsistent += 1
            elif cell.assessment == "consistent":
                consistent += 1
        scores.append(
            HypothesisScore(row.hypothesis, round(inconsistency, 4), consistent, inconsistent)
        )
    # Stable sort: ascending inconsistency, then more-consistent first as a weak tiebreak.
    return sorted(scores, key=lambda s: (s.inconsistency, -s.consistent))


def _label_reliability(evidence: list[EvidenceItem]) -> list[tuple[str, EvidenceItem]]:
    labels = evidence_labels(evidence)  # E1 -> doc_id
    by_id = {e.doc_id: e for e in evidence}
    return [(label, by_id[doc_id]) for label, doc_id in labels.items() if doc_id in by_id]


def neutral_matrix(hypotheses: list[str]) -> AchMatrix:
    """An all-neutral matrix — the honest fallback when no model scored the evidence:
    no diagnostic signal, so scoring leaves the hypotheses in their proposed order."""
    from argus.agent.schemas import AchRow

    return AchMatrix(rows=[AchRow(hypothesis=h, cells=[]) for h in hypotheses])


def render_ranking(scores: list[HypothesisScore]) -> str:
    """One line per hypothesis, strongest (least disconfirmed) first — for prompts/brief."""
    if not scores:
        return "(no hypotheses scored)"
    return "\n".join(
        f"{i + 1}. {s.hypothesis}  "
        f"(disconfirm={s.inconsistency:.2f}, -{s.inconsistent}/+{s.consistent})"
        for i, s in enumerate(scores)
    )
