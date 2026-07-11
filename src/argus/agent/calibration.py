"""Reliability-gated confidence cap — code-enforced calibration.

The model self-reports a confidence level, but a local model reliably over-reads a single
low-reliability source on a dramatic claim — the eval's calibration trap, where a lone
D-rated state-affiliated "foreign sabotage" report is rated *moderate* instead of *low*.
Rather than trust the prompt to hold the line, cap the reported confidence at what the
*sourcing* actually warrants, the same enforce-in-code discipline as citation resolvability.

The ceiling is computed from the distinct sources behind the brief (best Admiralty grade per
source, so one prolific outlet is still one source):

- **low**  — no source above the low tier (only D/E/F): uncorroborated, weak provenance.
- **moderate** — at least one credible (A-C) source, but not two independent reliable (A-B)
  ones: real but not strongly corroborated (single-source reporting lands here).
- **high** — two or more independent reliable (A-B) sources corroborate.

The cap only ever LOWERS the model's stated confidence, never raises it — a well-sourced
"moderate" stays moderate. Deterministic; no LLM.
"""

from argus.agent.state import EvidenceItem

# Admiralty source reliability A (best) .. F (cannot be judged) -> ordinal rank.
_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "F": 0}
_ORDER = {"low": 0, "moderate": 1, "high": 2}
_CREDIBLE = 3  # C or better
_RELIABLE = 4  # B or better


def _rank(reliability: str | None) -> int:
    return _RANK.get((reliability or "F").strip().upper()[:1], 0)


def confidence_ceiling(evidence: list[EvidenceItem]) -> tuple[str, str | None]:
    """The highest confidence the sourcing warrants, and why it caps below 'high' (None if
    it doesn't). Grades by *distinct source*, not document count."""
    best_by_source: dict[str, int] = {}
    for e in evidence:
        best_by_source[e.source] = max(best_by_source.get(e.source, -1), _rank(e.reliability))
    if not best_by_source:
        return "low", "no rated sourcing behind the assessment"
    credible = sum(1 for r in best_by_source.values() if r >= _CREDIBLE)
    reliable = sum(1 for r in best_by_source.values() if r >= _RELIABLE)
    if credible == 0:
        return "low", "only low-reliability (D/E/F) sourcing"
    if reliable >= 2:
        return "high", None
    if len(best_by_source) == 1:
        return "moderate", "single-source reporting"
    return "moderate", "no two independent reliable sources corroborate"


def apply_confidence_cap(
    confidence: str | None, evidence: list[EvidenceItem], citations: list[str] | None = None
) -> tuple[str | None, str | None]:
    """Return (possibly-lowered confidence, note). The note is set only when the cap
    actually lowered the model's stated level — surfaced to the analyst for transparency.

    Caps on the *cited* evidence (the actual basis for the judgments) when citations are
    given, falling back to all gathered evidence."""
    if confidence is None:
        return None, None
    cited_set = set(citations or [])
    basis = [e for e in evidence if e.doc_id in cited_set] if cited_set else evidence
    basis = basis or evidence  # citations that don't resolve to evidence -> use all
    ceiling, reason = confidence_ceiling(basis)
    if _ORDER.get(confidence.lower(), 2) > _ORDER[ceiling]:
        return ceiling, reason
    return confidence, None
