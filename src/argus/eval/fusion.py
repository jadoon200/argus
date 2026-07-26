"""Deterministic evaluation of supervisor lane selection."""

from dataclasses import dataclass

from argus.agent.supervisor import Lane, route_domains


@dataclass(frozen=True)
class RoutingCase:
    query: str
    expected: frozenset[Lane]


@dataclass(frozen=True)
class RoutingMetrics:
    precision: float
    recall: float
    exact_match: float
    cases: int
    errors: tuple[str, ...]


ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase("Assess suspicious vessels in the Singapore Strait", frozenset({"osint", "ocean"})),
    RoutingCase("Assess GNSS jamming affecting regional aviation", frozenset({"osint", "sky"})),
    RoutingCase("Who is behind the ransomware exploitation wave?", frozenset({"osint", "cyber"})),
    RoutingCase(
        "Are aircraft and naval vessels coordinating near the reef?",
        frozenset({"osint", "sky", "ocean"}),
    ),
    RoutingCase(
        "What did the governing coalition decide after the election?", frozenset({"osint"})
    ),
    RoutingCase("Any updates?", frozenset({"osint", "sky", "ocean", "cyber"})),
    RoutingCase("Give me an overview of the ocean from PHAROS", frozenset({"ocean"})),
    RoutingCase("Give me an overview of the sky from HORUS", frozenset({"sky"})),
    RoutingCase("Summarize cyber threats from SENTINEL", frozenset({"cyber"})),
    RoutingCase("Assess the disputed reef using OSINT", frozenset({"osint"})),
    RoutingCase("Compare PHAROS with SENTINEL", frozenset({"ocean", "cyber"})),
)


def evaluate_routing(cases: tuple[RoutingCase, ...] = ROUTING_CASES) -> RoutingMetrics:
    """Micro precision/recall plus exact-query accuracy over a hand-labelled lane set."""
    true_positive = false_positive = false_negative = exact = 0
    errors: list[str] = []
    for case in cases:
        predicted, _ = route_domains(case.query)
        true_positive += len(predicted & case.expected)
        false_positive += len(predicted - case.expected)
        false_negative += len(case.expected - predicted)
        if predicted == case.expected:
            exact += 1
        else:
            errors.append(
                f"{case.query}: expected {sorted(case.expected)}, got {sorted(predicted)}"
            )
    precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive else 0.0
    return RoutingMetrics(
        precision=precision,
        recall=recall,
        exact_match=exact / len(cases) if cases else 0.0,
        cases=len(cases),
        errors=tuple(errors),
    )
