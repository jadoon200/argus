from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARGUS_", env_file=".env", extra="ignore")

    # Host port 5433 by default so ARGUS's Postgres coexists with SENTINEL's (5432).
    database_url: str = "postgresql+psycopg://argus:argus@localhost:5433/argus"

    http_timeout_seconds: float = 30.0

    # --- Collection: GDELT DOC 2.0 API (free, no key, query-driven) -------------------
    gdelt_api_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    # Articles per query pull (GDELT caps at 250); English by default, recent first.
    gdelt_max_records: int = 75
    gdelt_timespan: str = "1w"  # e.g. 24h, 3d, 1w, 1m — recency window for a pull
    gdelt_source_lang: str = "english"

    # --- Collection: curated world / agency RSS feeds, keyed by provenance label ------
    # Each document is tagged with its feed label; the label keys the Admiralty
    # source-reliability map in nlp/reliability.py. One broken feed is skipped, not fatal.
    rss_feeds: dict[str, str] = {
        "bbc-world": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "guardian-world": "https://www.theguardian.com/world/rss",
        "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "npr-world": "https://feeds.npr.org/1004/rss.xml",
        "dw-world": "https://rss.dw.com/rdf/rss-en-world",
        "france24": "https://www.france24.com/en/rss",
        "channelnewsasia": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml",
        "un-news": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
        "reliefweb": "https://reliefweb.int/updates/rss.xml",
    }

    # --- Analysis (Layer 2a) ----------------------------------------------------------
    # Free local sentence-transformer for dense retrieval + clustering embeddings.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_cache_dir: Path = Path("data/embedding_cache")
    # Named-entity recognition backend: "spacy" (needs the nlp extra + a model) or
    # "heuristic" (dependency-free fallback). Auto-falls back to heuristic if spaCy
    # or its model is unavailable, so the pipeline always runs.
    ner_backend: str = "spacy"
    spacy_model: str = "en_core_web_sm"
    # Event dedup: two documents merge into one event above this title/summary cosine
    # and within this many days of each other.
    event_dedup_threshold: float = 0.78
    event_window_days: float = 3.0
    # Hybrid retrieval: reciprocal-rank-fusion constant and default depth.
    retrieval_top_k: int = 10
    rrf_k: int = 60

    # --- Narrative watch (Layer 2b) ---------------------------------------------------
    narrative_min_cluster_size: int = 3
    # Looser than event dedup: a narrative is a shared *framing/claim*, not the same event.
    narrative_threshold: float = 0.6
    # Coordination: window (hours) within which synchronized publishing looks coordinated.
    coordination_window_hours: float = 6.0

    # --- Analyst agent (Layer 3) ------------------------------------------------------
    # auto -> local Ollama if reachable, else the deterministic template backend.
    # auto NEVER selects a remote/paid backend (zero-cost by default). Explicit values:
    # "ollama" | "mlx" | "openai" | "anthropic" | "template" | "auto".
    llm_backend: str = "auto"
    # Paid, strictly opt-in: only read as ARGUS_ANTHROPIC_API_KEY, and only used when
    # llm_backend is explicitly "anthropic". Unset -> the paid path cannot be reached.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"
    ollama_url: str = "http://localhost:11434"
    # Preferred Ollama model; the backend auto-falls back to any installed model if
    # this one is absent (so the agent runs with whatever the user has pulled).
    ollama_model: str = "llama3.1"
    # Apple-Silicon-native local inference via mlx-lm (free; the `mlx` extra). The path
    # to serving a locally fine-tuned model. Opt-in: ARGUS_LLM_BACKEND=mlx.
    mlx_model: str = "mlx-community/Qwen2.5-14B-Instruct-4bit"
    # Optional LoRA adapter (from `make finetune`) loaded on top of mlx_model.
    mlx_adapter_path: str | None = None
    # Self-distillation fine-tuning: a small student learns ARGUS-style briefs from the
    # teacher's eval-passing outputs (see argus/finetune/ and docs/FINETUNE.md).
    finetune_base_model: str = "mlx-community/Qwen2.5-3B-Instruct-4bit"
    finetune_data_dir: str = "data/finetune"
    finetune_iters: int = 300
    # OpenAI-compatible server (vLLM / llama.cpp / LM Studio / groq / together). Free
    # when pointed at a local server; opt-in: ARGUS_LLM_BACKEND=openai.
    openai_base_url: str = "http://localhost:8000/v1"
    openai_api_key: str | None = None  # a local server usually ignores this
    openai_model: str = "local-model"
    # Agents deliberate (multiple LLM calls); give them room rather than racing them.
    llm_timeout_seconds: float = 180.0
    brief_context_docs: int = 12  # documents of evidence handed to the agents per query
    # Source diversity: cap how many evidence items any single source contributes to a
    # brief, so one prolific outlet can't dominate the agents' evidence (on-theme with the
    # reliability/coordination focus). 0 disables the cap.
    brief_max_per_source: int = 3
    num_hypotheses: int = 3  # competing hypotheses the ACH stage generates
    debate_rounds: int = 1  # red-team challenges, each followed by an analyst rebuttal
    # Brief generation path: "panel" = the multi-agent ACH deliberation (default);
    # "dspy" = the optimized single-shot DSPy program (the `optimize` extra; falls back to
    # an unoptimized program if `make optimize` hasn't produced data/dspy/); "student" =
    # one-shot the configured backend with the training prompt (the MLX-distilled student).
    brief_mode: str = "panel"

    # --- Sibling bridge: SENTINEL cyber knowledge-graph API (read-only) ---------------
    # Empty disables the query_cyber_graph agent tool.
    sentinel_api_url: str = ""
    # Query-relevant cyber fusion: map the brief's query through SENTINEL's /map-techniques
    # and keep only campaigns whose ATT&CK techniques overlap the techniques mapped above
    # this score. Calibrated so a cyber query (~0.35) pulls relevant campaigns while a
    # geopolitical one (~0.08) pulls none. 0 keeps the old query-agnostic top-salient behaviour.
    sentinel_relevance_min_score: float = 0.25

    # --- API hardening for public deployment (safe local-dev defaults) ----------------
    api_allowed_origins: str = ""
    api_max_request_chars: int = 4_000
    api_rate_limit_requests: int = 20
    api_rate_limit_window_seconds: float = 60.0
    api_trust_forwarded_header: bool = False
    api_inference_concurrency: int = 2
    api_inference_acquire_timeout_seconds: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
