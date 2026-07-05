from argus.actors import (
    THREAT_ACTORS,
    actors_for_nation,
    attributions_in_text,
    resolve_actor,
)


def test_registry_integrity() -> None:
    names = [a.name for a in THREAT_ACTORS]
    assert len(names) == len(set(names))  # unique canonical names
    all_names = [n.lower() for a in THREAT_ACTORS for n in a.names]
    assert len(all_names) == len(set(all_names))  # no alias collides across actors


def test_resolve_by_name_and_alias() -> None:
    apt28 = resolve_actor("APT28")
    assert apt28 is not None and apt28.nation == "Russia"
    assert resolve_actor("fancy bear") is apt28  # alias, case-insensitive
    cozy = resolve_actor("Cozy Bear")
    assert cozy is not None and cozy.name == "APT29"
    assert resolve_actor("not a real group") is None


def test_attributions_in_text_finds_and_dedupes() -> None:
    text = "Reporting links the intrusion to Sandworm and Fancy Bear, both tied to the GRU."
    actors = attributions_in_text(text)
    assert {a.name for a in actors} == {"Sandworm", "APT28"}
    assert {a.nation for a in actors} == {"Russia"}


def test_attribution_respects_word_boundaries() -> None:
    # "APT1" must not match inside "APT10".
    assert [a.name for a in attributions_in_text("the APT10 campaign")] == ["APT10"]
    hit = attributions_in_text("APT1 was first documented")
    assert hit and hit[0].name == "APT1"


def test_common_short_form_lazarus_resolves() -> None:
    # CTI text usually says just "Lazarus" — the bare form must scan (recall bug, fixed).
    hits = attributions_in_text("Lazarus stole $600M from the bridge")
    assert [a.name for a in hits] == ["Lazarus Group"]


def test_generic_word_aliases_do_not_false_positive() -> None:
    # Ordinary prose must never be attributed to a state (false-positive bug, fixed).
    assert attributions_in_text("Zinc mining output rose in Peru") == []
    assert attributions_in_text("a snake was found in the datacenter") == []
    assert attributions_in_text("phosphorus levels in the river") == []
    assert attributions_in_text("the Iridium satellite constellation") == []
    assert attributions_in_text("cicada season begins in June") == []
    # ...but the distinctive all-caps vendor form still resolves (case-sensitive gate).
    zinc = attributions_in_text("ZINC targets security researchers")
    assert [a.name for a in zinc] == ["Lazarus Group"]


def test_actors_for_nation() -> None:
    russia = {a.name for a in actors_for_nation("russia")}  # case-insensitive
    assert {"APT28", "APT29", "Sandworm", "Turla"} <= russia
    assert actors_for_nation("Atlantis") == []
