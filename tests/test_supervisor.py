from argus.agent.supervisor import ALL_LANES, route_domains


def test_ocean_query_routes_to_osint_and_ocean() -> None:
    lanes, reason = route_domains("Assess suspicious vessels in the Singapore Strait")
    assert lanes == {"osint", "ocean"}
    assert "ocean matched" in reason and "vessel" in reason


def test_sky_query_routes_to_osint_and_sky() -> None:
    lanes, reason = route_domains("Assess GNSS jamming affecting regional aviation")
    assert lanes == {"osint", "sky"}
    assert "sky matched" in reason and "gnss" in reason


def test_cyber_query_routes_to_osint_and_cyber() -> None:
    lanes, reason = route_domains("Who is behind the ransomware exploitation wave?")
    assert lanes == {"osint", "cyber"}
    assert "cyber matched" in reason and "ransomware" in reason


def test_subjectless_followup_routes_every_lane() -> None:
    lanes, reason = route_domains("Any updates?")
    assert lanes == set(ALL_LANES)
    assert "subject-less" in reason and "every lane" in reason


def test_political_query_stays_on_osint() -> None:
    lanes, reason = route_domains("What did the governing coalition decide after the election?")
    assert lanes == {"osint"}
    assert "base lane only" in reason


def test_cross_domain_query_wakes_multiple_workers() -> None:
    lanes, _ = route_domains("Are aircraft and naval vessels coordinating near the reef?")
    assert lanes == {"osint", "sky", "ocean"}


def test_lane_and_project_names_route_to_their_lane() -> None:
    """The user refers to lanes by name ("sky", "horus", "pharos", "sentinel"); those must
    route even when no other domain vocabulary is present. Regression for a live miss where
    "the most major incident in the sky for horus" fell back to OSINT-only."""
    assert route_domains("the most major incident in the sky for horus")[0] == {"osint", "sky"}
    assert route_domains("what is pharos tracking right now")[0] == {"osint", "ocean"}
    assert route_domains("summarize the latest from sentinel")[0] == {"osint", "cyber"}
    assert route_domains("anything airborne worth a look")[0] == {"osint", "sky"}
