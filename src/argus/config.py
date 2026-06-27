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
    # Event dedup: two documents merge into one event above this title/summary cosine.
    event_dedup_threshold: float = 0.78
    # Hybrid retrieval: reciprocal-rank-fusion constant and default depth.
    retrieval_top_k: int = 10
    rrf_k: int = 60

    # --- Narrative watch (Layer 2b) ---------------------------------------------------
    narrative_min_cluster_size: int = 3
    # Coordination: window (hours) within which synchronized publishing looks coordinated.
    coordination_window_hours: float = 6.0

    # --- Analyst agent (Layer 3) ------------------------------------------------------
    # auto -> Claude if a key is present, else ollama if reachable, else template.
    # Explicit values: "anthropic" | "ollama" | "mlx" | "template".
    llm_backend: str = "auto"
    anthropic_api_key: str | None = None  # also read from ANTHROPIC_API_KEY (see agent/llm.py)
    anthropic_model: str = "claude-opus-4-8"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    mlx_model: str = "mlx-community/Llama-3.1-8B-Instruct-4bit"
    brief_context_docs: int = 12  # documents handed to the briefer per query

    # --- Sibling bridge: SENTINEL cyber knowledge-graph API (read-only) ---------------
    # Empty disables the query_cyber_graph agent tool.
    sentinel_api_url: str = ""

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
