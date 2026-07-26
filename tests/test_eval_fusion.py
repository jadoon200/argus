from argus.eval.fusion import ROUTING_CASES, RoutingCase, evaluate_routing


def test_fusion_routing_goldset_is_exact_on_v1_profiles() -> None:
    metrics = evaluate_routing()
    assert metrics.cases == len(ROUTING_CASES) >= 6
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.exact_match == 1.0
    assert metrics.errors == ()


def test_fusion_routing_eval_records_false_positive_and_negative() -> None:
    # A deliberately wrong label proves the metric does not mechanically report 1.0.
    wrong = (RoutingCase("Ransomware campaign", frozenset({"osint", "sky"})),)
    metrics = evaluate_routing(wrong)
    assert 0.0 < metrics.precision < 1.0
    assert 0.0 < metrics.recall < 1.0
    assert metrics.exact_match == 0.0 and metrics.errors
