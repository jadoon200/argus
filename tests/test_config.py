from argus.config import Settings


def test_defaults_are_zero_cost_safe() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    # No key required by default; the agent falls back to a local/deterministic backend.
    assert s.anthropic_api_key is None
    assert s.llm_backend == "auto"
    # Sibling cyber bridge is off unless explicitly pointed at SENTINEL.
    assert s.sentinel_api_url == ""
    # Curated feeds are present and keyed by provenance label.
    assert "bbc-world" in s.rss_feeds


def test_env_prefix_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ARGUS_LLM_BACKEND", "template")
    monkeypatch.setenv("ARGUS_GDELT_MAX_RECORDS", "10")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.llm_backend == "template"
    assert s.gdelt_max_records == 10
