"""Deterministic, cross-family faithfulness/citation scoring via natural-language inference.

The LLM-as-judge (`judge.py`) has two recorded weaknesses: it is *stochastic* (run-to-run
swing on the same brief) and *self-biased* (the generator's own model family scoring its own
briefs). This scorer answers the same two questions — is a judgment *grounded* in the
evidence, does its *cited* evidence *support* it — with claim-level NLI entailment instead:

- **Deterministic.** A cross-encoder entailment probability is a fixed function of (premise,
  hypothesis); the same brief scores the same number every run.
- **Cross-family.** A dedicated NLI model (`cross-encoder/nli-deberta-v3-base`), not the
  generator, removes the self-judging bias.

Method (the RAGAS/claim-level recipe): each key judgment is a hypothesis; each evidence item is
a premise. A judgment is *grounded* if ANY evidence entails it; *supported* if the specific
[E#] item(s) it cites entail it. Free/local, opt-in (`ARGUS_NLI_ENABLED`) so CI never pulls a
model. `ENTAILMENT_GOLD` + `agreement()` let us measure the scorer against human labels — the
honest "does the judge agree with a human" check the LLM judge leaves open.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from argus.agent.state import EvidenceItem, evidence_labels
from argus.eval.judge import JudgeScores
from argus.eval.metrics import citation_markers
from argus.logging import get_logger

log = get_logger(__name__)

_MARKER = re.compile(r"\[[^\]]*\]")


class NliScorer(Protocol):
    def predict_entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Entailment probability in [0,1] for each (premise, hypothesis) pair."""
        ...


def _evidence_text(item: EvidenceItem) -> str:
    return f"{item.title}. {item.summary or ''}".strip()


def _claim_text(judgment: str) -> str:
    """The bare claim: the judgment with its [E#] citation markers stripped."""
    return _MARKER.sub("", judgment).strip()


def score_brief_nli(
    judgments: list[str],
    evidence: list[EvidenceItem],
    scorer: NliScorer,
    threshold: float = 0.5,
) -> JudgeScores:
    """Grounded/supported counts by NLI entailment (deterministic; mirrors judge.JudgeScores)."""
    scores = JudgeScores()
    if not evidence:
        return scores
    labels = evidence_labels(evidence)  # {"E1": doc_id, ...}
    by_label = {label: evidence[i] for i, label in enumerate(labels)}
    ev_texts = [_evidence_text(e) for e in evidence]

    for judgment in judgments:
        claim = _claim_text(judgment)
        if not claim:
            continue
        # Grounded: does ANY evidence item entail the claim?
        probs = scorer.predict_entailment([(text, claim) for text in ev_texts])
        grounded = any(p >= threshold for p in probs)
        # Supported: do the SPECIFIC cited [E#] items entail it? (false if it cites nothing)
        cited = [by_label[m] for m in citation_markers(judgment) if m in by_label]
        if cited:
            cited_probs = scorer.predict_entailment([(_evidence_text(e), claim) for e in cited])
            supported = any(p >= threshold for p in cited_probs)
        else:
            supported = False
        scores.n += 1
        scores.grounded += int(grounded)
        scores.supported += int(supported)
    return scores


class CrossEncoderNli:
    """Lazy `sentence-transformers` cross-encoder NLI scorer (free, local).

    `nli-deberta-v3-base` emits 3 logits ordered [contradiction, entailment, neutral]; we
    softmax and return the entailment probability. The model downloads on first use, so this
    is constructed only when NLI scoring is explicitly enabled.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            log.info("loading_nli", model=self._model_name)
            self._model = CrossEncoder(self._model_name)
        return self._model

    def predict_entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        model = self._get_model()
        logits = np.atleast_2d(np.asarray(model.predict(list(pairs))))  # type: ignore[attr-defined]
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        probs = exp / exp.sum(axis=1, keepdims=True)
        return [float(p) for p in probs[:, 1]]  # index 1 = entailment


def load_nli_scorer(model_name: str) -> CrossEncoderNli | None:
    """Construct the NLI scorer; None if sentence-transformers is unavailable."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return None
    return CrossEncoderNli(model_name)


# --- judge-vs-human agreement slice --------------------------------------------------
@dataclass(frozen=True)
class EntailmentCase:
    premise: str  # an evidence line
    hypothesis: str  # a claim
    entailed: bool  # the human label


# A small hand-labelled slice grounded in the gold-set scenarios. Several encode the
# allegation-vs-fact distinction that is the whole calibration point: an outlet *alleging*
# sabotage does NOT entail that sabotage *happened*.
ENTAILMENT_GOLD: list[EntailmentCase] = [
    EntailmentCase(
        "Two coast guard ships confronted fishing boats at the contested reef on Tuesday.",
        "Coast guard vessels were involved in a standoff at the disputed reef.",
        True,
    ),
    EntailmentCase(
        "Two coast guard ships confronted fishing boats at the contested reef on Tuesday.",
        "The navy sank a fishing boat at the reef.",
        False,
    ),
    EntailmentCase(
        "State outlet cited unnamed officials blaming foreign sabotage for the blackout.",
        "Foreign sabotage caused the nationwide blackout.",
        False,
    ),
    EntailmentCase(
        "State outlet cited unnamed officials blaming foreign sabotage for the blackout.",
        "A state-affiliated outlet alleged foreign sabotage caused the blackout.",
        True,
    ),
    EntailmentCase(
        "The central bank kept its benchmark interest rate unchanged, citing easing inflation.",
        "The central bank held interest rates steady.",
        True,
    ),
    EntailmentCase(
        "The central bank kept its benchmark interest rate unchanged, citing easing inflation.",
        "The central bank raised interest rates.",
        False,
    ),
    EntailmentCase(
        "International observers certified the election result as credible.",
        "Independent observers found the election credible.",
        True,
    ),
    EntailmentCase(
        "A border clash was reported; independent accounts of which side fired first differ.",
        "Country A fired first in the border clash.",
        False,
    ),
    EntailmentCase(
        "Rescue teams searched collapsed buildings for survivors after the capital earthquake.",
        "An earthquake struck the capital and caused buildings to collapse.",
        True,
    ),
    EntailmentCase(
        "Unverified anonymous social posts alleged armored columns were moving to the border.",
        "Armored columns are confirmed to be moving to the border.",
        False,
    ),
]


def agreement(
    scorer: NliScorer, cases: Sequence[EntailmentCase] = ENTAILMENT_GOLD, threshold: float = 0.5
) -> float:
    """Fraction of the labelled slice where the scorer's entail/not call matches the human."""
    if not cases:
        return 1.0
    probs = scorer.predict_entailment([(c.premise, c.hypothesis) for c in cases])
    correct = sum((p >= threshold) == c.entailed for p, c in zip(probs, cases, strict=True))
    return correct / len(cases)
