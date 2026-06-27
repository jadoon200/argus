import pytest

from argus.agent.llm import (
    OllamaBackend,
    _resolve_ollama_model,
    ollama_models,
    resolve_backend,
)
from argus.config import Settings


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_template_choice_returns_none() -> None:
    assert resolve_backend(_settings(llm_backend="template")) is None


def test_auto_prefers_ollama_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "argus.agent.llm.ollama_models", lambda url, timeout=3.0: ["llama3.1:latest"]
    )
    backend = resolve_backend(_settings(llm_backend="auto"))
    assert isinstance(backend, OllamaBackend)
    assert backend.name == "ollama:llama3.1:latest"


def test_auto_never_selects_anthropic_even_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Free-by-default: auto must not spend money even if a key is present.
    monkeypatch.setattr("argus.agent.llm.ollama_models", lambda url, timeout=3.0: [])
    backend = resolve_backend(_settings(llm_backend="auto", anthropic_api_key="sk-test"))
    assert backend is None


def test_resolve_ollama_model_prefers_then_falls_back() -> None:
    assert (
        _resolve_ollama_model("llama3.1", ["llama2:latest", "llama3.1:latest"]) == "llama3.1:latest"
    )
    assert (
        _resolve_ollama_model("llama3.1", ["llama2:latest"]) == "llama2:latest"
    )  # first available
    assert _resolve_ollama_model("qwen2.5:7b", ["qwen2.5:7b"]) == "qwen2.5:7b"  # exact


def test_ollama_models_unreachable_returns_empty() -> None:
    assert ollama_models("http://127.0.0.1:1", timeout=0.5) == []
