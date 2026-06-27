"""NATO Admiralty System scoring + human-readable labels.

Two independent axes, shown to the analyst so provenance is never hidden:

* **Source reliability** (A-F) — a property of the *publisher*, assigned from the
  curated registry in `argus.sources`.
* **Information credibility** (1-6) — a property of an *item of information*. Here it
  is computed as a **corroboration proxy**: how many *independent* sources report the
  same event (the event clusters from `nlp.events`). It is explicitly NOT a truth
  judgment — it only reflects independent corroboration, and is labelled as such.
"""

# Admiralty source-reliability grades (mirrors argus.sources).
RELIABILITY_LABELS: dict[str, str] = {
    "A": "completely reliable",
    "B": "usually reliable",
    "C": "fairly reliable",
    "D": "not usually reliable",
    "E": "unreliable",
    "F": "reliability cannot be judged",
}

# Admiralty information-credibility grades.
CREDIBILITY_LABELS: dict[int, str] = {
    1: "confirmed by other sources",
    2: "probably true",
    3: "possibly true",
    4: "uncorroborated (single source)",
    6: "cannot be judged",
}


def credibility_from_corroboration(source_count: int) -> int:
    """Map independent-source corroboration count to an Admiralty credibility grade.

    A corroboration proxy, not a truth judgment: more independent sources reporting
    the same event -> a lower (more credible) grade. `source_count` is the number of
    *distinct* sources in the document's event cluster (>=1 once clustered; 0/absent
    means un-enriched -> "cannot be judged").
    """
    if source_count >= 4:
        return 1
    if source_count == 3:
        return 2
    if source_count == 2:
        return 3
    if source_count == 1:
        return 4
    return 6


def reliability_label(grade: str) -> str:
    return RELIABILITY_LABELS.get(grade.upper(), RELIABILITY_LABELS["F"])


def credibility_label(grade: int | None) -> str:
    return CREDIBILITY_LABELS.get(grade or 6, CREDIBILITY_LABELS[6])


def admiralty_code(reliability: str, credibility: int | None) -> str:
    """The compact Admiralty rating, e.g. 'B2'. Defaults to F6 when unknown."""
    grade = reliability.upper() if reliability else "F"
    return f"{grade}{credibility or 6}"
