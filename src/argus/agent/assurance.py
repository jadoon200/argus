"""Self-consistency confidence calibration (opt-in high-assurance mode).

A single adjudication is stochastic — the confidence call can drift low↔moderate between
runs on the same evidence. Self-consistency (Wang et al., 2022) samples the adjudicator K
times and derives the *reported* confidence from AGREEMENT: if the panel keeps landing on
the same call, that is genuine confidence; if it wobbles, the honest confidence is lower.

Costs K adjudicator calls, so it is opt-in via `ARGUS_ASSURANCE_SAMPLES > 1`. The
resampling reuses the exact adjudicator context (`nodes.adjudicator_prompt`) but samples
at a non-zero temperature so the runs can actually differ.
"""

from collections import Counter

from argus.agent import nodes
from argus.agent.llm import LLMBackend
from argus.agent.personas import ADJUDICATOR_SYSTEM
from argus.agent.schemas import Finding
from argus.agent.state import DeliberationState
from argus.agent.structured import complete_model

_ORDER = {"low": 0, "moderate": 1, "high": 2}
_LEVEL = {0: "low", 1: "moderate", 2: "high"}


def calibrate(confidences: list[str]) -> tuple[str, float]:
    """Modal confidence, downgraded one level if the samples don't mostly agree.

    Returns (calibrated_confidence, agreement in [0,1]). Agreement is the share of samples
    that hit the modal value; below 2/3 the model can't commit, so we report one level
    lower — calibration honesty over a lucky single draw.
    """
    if not confidences:
        return "low", 0.0
    modal, hits = Counter(confidences).most_common(1)[0]
    agreement = hits / len(confidences)
    level = _ORDER.get(modal, 0)
    if agreement < 2 / 3 and level > 0:
        level -= 1
    return _LEVEL[level], round(agreement, 2)


def assured_confidence(
    state: DeliberationState, backend: LLMBackend, samples: int, temperature: float
) -> tuple[str, float] | None:
    """Sample the adjudicator `samples` times and calibrate the confidence from agreement.

    Returns None when no resample parses (backend timeout, malformed JSON) so the caller
    keeps the primary finding's confidence — assurance can refine a confidence call, never
    replace a successful one with a fabricated "low" — never worse than one-shot behaviour.
    """
    prompt = nodes.adjudicator_prompt(state)
    confidences: list[str] = []
    for _ in range(max(1, samples)):
        finding: Finding | None = complete_model(
            backend, ADJUDICATOR_SYSTEM, prompt, Finding, temperature=temperature
        )
        if finding is not None and finding.key_judgments:
            confidences.append(finding.confidence)
    if not confidences:
        return None
    return calibrate(confidences)
