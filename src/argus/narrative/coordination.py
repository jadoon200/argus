"""Coordination scoring for a narrative cluster.

A transparent heuristic, in [0,1], for how *synchronized* and *low-reliability-heavy* the
pushing of a narrative is. It is a HUMAN-REVIEW SIGNAL — a prompt for an analyst to look
closer — never an automated verdict of inauthenticity. Organic breaking-news coverage is
also bursty; the low-reliability share is what separates likely amplification from it.
"""

from datetime import datetime, timedelta

_LOW_RELIABILITY = {"D", "E", "F"}


def burstiness(times: list[datetime | None], window: timedelta) -> float:
    """Max fraction of documents falling within any single `window`-wide span."""
    known = sorted(t for t in times if t is not None)
    n = len(times)
    if n == 0 or len(known) < 2:
        return 0.0
    max_in_window, left = 1, 0
    for right in range(len(known)):
        while known[right] - known[left] > window:
            left += 1
        max_in_window = max(max_in_window, right - left + 1)
    return max_in_window / n


def low_reliability_share(reliabilities: list[str]) -> float:
    if not reliabilities:
        return 0.0
    low = sum(1 for r in reliabilities if r.upper() in _LOW_RELIABILITY)
    return low / len(reliabilities)


def coordination_score(
    times: list[datetime | None], reliabilities: list[str], window: timedelta
) -> float:
    """Synchronization, weighted up when low-reliability sources dominate.

    coordination = burstiness * (0.5 + 0.5 * low_reliability_share), so a bursty but
    well-sourced story is dampened while a bursty, state-affiliated-heavy push is not.
    """
    burst = burstiness(times, window)
    weight = 0.5 + 0.5 * low_reliability_share(reliabilities)
    return round(burst * weight, 4)
