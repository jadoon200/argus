from collections.abc import Sequence

from argus.agent.state import EvidenceItem
from argus.eval.nli import (
    ENTAILMENT_GOLD,
    EntailmentCase,
    _claim_text,
    agreement,
    score_brief_nli,
)


class KeywordNli:
    """Deterministic fake NLI scorer: entails iff the hypothesis's keyword is in the premise.
    Lets the claim-level logic be tested with no model download."""

    def __init__(self, keyword: str) -> None:
        self._kw = keyword.lower()

    def predict_entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [1.0 if self._kw in premise.lower() else 0.0 for premise, _ in pairs]


def _ev(doc_id: str, title: str, summary: str) -> EvidenceItem:
    return EvidenceItem(
        doc_id=doc_id,
        title=title,
        source="reuters.com",
        reliability="B",
        credibility=2,
        summary=summary,
    )


def test_claim_text_strips_citation_markers() -> None:
    out = _claim_text("The reef standoff escalated [E1] [E2].")
    assert "[E1]" not in out and "[E2]" not in out
    assert out.startswith("The reef standoff escalated")


def test_grounded_and_supported_when_cited_evidence_entails() -> None:
    evidence = [
        _ev("a:1", "Reef standoff", "coast guard vessels confronted boats at the reef"),
        _ev("b:2", "Heatwave", "temperature records across Europe"),
    ]
    scorer = KeywordNli("coast guard")
    # Judgment cites E1 (the reef item) -> grounded (some ev entails) AND supported (cited entails).
    scores = score_brief_nli(["Coast guard vessels were in a standoff [E1]."], evidence, scorer)
    assert scores.n == 1
    assert scores.faithfulness == 1.0
    assert scores.citation_support == 1.0


def test_grounded_but_not_supported_when_wrong_item_cited() -> None:
    evidence = [
        _ev("a:1", "Reef standoff", "coast guard vessels confronted boats at the reef"),
        _ev("b:2", "Heatwave", "temperature records across Europe"),
    ]
    scorer = KeywordNli("coast guard")
    # Claim is grounded (E1 entails) but cites E2 (the heatwave) -> supported must be False.
    scores = score_brief_nli(["Coast guard vessels were in a standoff [E2]."], evidence, scorer)
    assert scores.faithfulness == 1.0
    assert scores.citation_support == 0.0


def test_uncited_claim_is_unsupported() -> None:
    evidence = [_ev("a:1", "Reef standoff", "coast guard vessels confronted boats at the reef")]
    scorer = KeywordNli("coast guard")
    scores = score_brief_nli(["Coast guard vessels were in a standoff."], evidence, scorer)
    assert scores.faithfulness == 1.0  # grounded
    assert scores.citation_support == 0.0  # cites nothing


def test_ungrounded_claim() -> None:
    evidence = [_ev("a:1", "Reef standoff", "coast guard vessels confronted boats at the reef")]
    scorer = KeywordNli("sabotage")  # nothing in evidence mentions sabotage
    scores = score_brief_nli(["Foreign sabotage caused the blackout [E1]."], evidence, scorer)
    assert scores.faithfulness == 0.0
    assert scores.citation_support == 0.0


def test_entailment_gold_is_balanced() -> None:
    assert len(ENTAILMENT_GOLD) >= 8
    entailed = [c for c in ENTAILMENT_GOLD if c.entailed]
    # A useful agreement slice needs both entail and non-entail cases.
    assert 0 < len(entailed) < len(ENTAILMENT_GOLD)


def test_agreement_perfect_and_imperfect() -> None:
    cases = [
        EntailmentCase("the sky is blue", "sky is blue", True),
        EntailmentCase("the cat sat", "a dog ran", False),
    ]
    # "sky" is in premise 1 only: predicts True (label True) then False (label False) -> both right.
    assert agreement(KeywordNli("sky"), cases) == 1.0
    # "the" is in both premises: predicts True for both -> right on case 1, wrong on case 2 -> 0.5.
    assert agreement(KeywordNli("the"), cases) == 0.5
