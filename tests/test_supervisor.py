from argus.agent.supervisor import ALL_LANES, route_domains


def test_ocean_query_routes_to_osint_and_ocean() -> None:
    lanes, reason = route_domains("Give me an overview of the ocean")
    assert lanes == {"osint", "ocean"}
    assert "ocean matched" in reason and "ocean" in reason


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


def test_generic_lane_names_fuse_with_osint() -> None:
    assert route_domains("the most major incident in the sky")[0] == {"osint", "sky"}
    assert route_domains("give me an overview of the ocean")[0] == {"osint", "ocean"}
    assert route_domains("anything airborne worth a look")[0] == {"osint", "sky"}


def test_named_source_systems_are_exclusive() -> None:
    cases = {
        "overview of the ocean from PHAROS": {"ocean"},
        "what is HORUS tracking right now": {"sky"},
        "summarize the latest from SENTINEL": {"cyber"},
        "assess the reef using OSINT": {"osint"},
        "assess the reef from open-source reporting": {"osint"},
    }
    for query, expected in cases.items():
        lanes, reason = route_domains(query)
        assert lanes == expected
        assert "explicit source scope" in reason and "consulted only" in reason


def test_multiple_named_sources_select_exactly_those_sources() -> None:
    lanes, reason = route_domains("Compare PHAROS with SENTINEL")
    assert lanes == {"ocean", "cyber"}
    assert "PHAROS/Ocean" in reason and "SENTINEL/Cyber" in reason

    lanes, _ = route_domains("Compare HORUS with OSINT reporting")
    assert lanes == {"osint", "sky"}


def test_explicit_all_source_request_overrides_named_source_scope() -> None:
    lanes, reason = route_domains("Give me an all-source overview including PHAROS")
    assert lanes == set(ALL_LANES)
    assert "all-source" in reason and "every lane" in reason
