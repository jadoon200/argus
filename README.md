# ARGUS

[![CI](https://github.com/jadoon200/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/jadoon200/argus/actions/workflows/ci.yml)

**All-source intelligence analyst workbench** — fuses the open-source *information*
environment (global news + events + advisories) into source-rated, **cited intelligence
briefs**, written by a **multi-agent ACH deliberation panel** and held to a measured
evaluation bar.

> **Sibling to [SENTINEL](../sentinel).** Sentinel fuses the **cyber** threat picture
> (network intrusions × ATT&CK × CTI). ARGUS fuses the **information** picture
> (open-source reporting × entities/events × narratives) and puts an **agentic analyst**
> on top. The two join: ARGUS can query Sentinel's cyber knowledge graph so one analyst
> reasons across both — the way an all-source fusion cell actually works.

> **Status:** agent spine, API, narrative watch, cyber-fusion bridge, and the React dashboard
> all complete (plus DSPy prompt optimization and MLX LoRA fine-tuning).
> What runs today and what's planned is tracked honestly in
> [`docs/ROADMAP.md`](docs/ROADMAP.md); every model/agent claim lands in
> [`docs/EVAL.md`](docs/EVAL.md) with the number that survives scrutiny, not a demo cherry-pick.

## What it does

Give it an analyst question — an actor, a region, an event, a timeframe — and it:

1. **Collects** open-source reporting on the topic (GDELT's global news index + curated
   world/agency RSS feeds — all free, no paid keys).
2. **Structures** it — extracts entities and events, deduplicates near-identical reports,
   and rates each source on the **NATO Admiralty System** (source reliability A–F ×
   information credibility 1–6), so corroboration and provenance are first-class.
3. **Deliberates a brief** — not a one-shot RAG summary. A **multi-agent panel** argues the
   judgment out using real intelligence tradecraft: a panel sets **competing hypotheses**, a
   lead **Analyst** makes the case, a **Red Team** attacks it (disconfirming evidence, weak
   sourcing, state-affiliated narratives), and an **Adjudicator** applies **Analysis of
   Competing Hypotheses** (favour the *least-disconfirmed* hypothesis) and issues a finding in
   the IC's estimative language (ICD 203 / Kent). The result is a structured brief — **key
   judgments, a confidence call, the most credible alternative + what would raise it, and
   honest intelligence gaps** — where **every citation resolves to a real ingested document**
   (fabricated citations are dropped, never shown). Built on LangGraph; runs **free** on a
   local Ollama model (Claude optional, never required), with a deterministic fallback so it
   always runs.
4. **Watches narratives** — clusters the reporting into narratives and flags
   **coordination** (suspiciously synchronized pushing of the same message), the
   information-defence half of the picture — surfaced at `GET /narratives` (most-coordinated
   first), as a human-review signal, never an automated verdict.
5. **Fuses the cyber picture** — when pointed at the sibling **SENTINEL** knowledge graph
   (`ARGUS_SENTINEL_API_URL`), pulls cyber campaigns in as citable evidence so one brief reasons
   across open-source *and* cyber reporting (read-only; off by default).

## Why it's built this way

- **Honest evaluation, not a demo.** The agent is *measured*: retrieval recall, **citation
  accuracy** (does each cited source actually exist and support the claim?), **faithfulness**
  (no ungrounded claims), and source-reliability calibration — with recorded **negatives**
  where it fails. This eval harness is the point; a RAG demo that nobody graded isn't an
  intelligence tool. See [`docs/EVAL.md`](docs/EVAL.md).
- **Zero-cost, runs offline.** Free data sources and free/local models only. The LLM layer is
  **pluggable**: local Ollama (`auto` mode; recommended: `qwen2.5:14b`) by default, a
  deterministic extractive fallback when Ollama is unreachable, and Claude (Anthropic API)
  as an **opt-in** via `ARGUS_LLM_BACKEND=anthropic` — never selected automatically.
  The product and test suite run end-to-end with **no API key at all**.
- **Source-rated, cited, transparent.** No claim without a citation; no source without a
  reliability rating. The Admiralty score is shown, not hidden.

## Responsible use

ARGUS is strictly **defensive and analytical**, over **public, open-source data only**. It
summarizes and rates open reporting to help an analyst; it does **not** target individuals,
scrape behind authentication, profile private persons, or produce any offensive capability.
Coordination signals flag *patterns in public posting* for human review — they are decision
support, never an automated verdict. This responsible-use posture is a design constraint, not
an afterthought.

## Architecture

```
 ┌────────────────────────────┐        ┌────────────────────────────┐
 │ Layer 1 · Collection       │        │  bridge → SENTINEL cyber KG │
 │ GDELT global news + events │        │  read-only API:/campaigns,  │
 │ + curated world/agency RSS │◄──────►│  /techniques (reuse as-is)  │
 │           → one corpus     │        └──────────────┬─────────────┘
 └─────────────┬──────────────┘                       │
               ▼                                       │
 ┌─────────────────────────────────────────────┐      │
 │ Layer 2 · Analysis                           │      │
 │  2a entities + events + Admiralty            │      │
 │     source-reliability scoring + retrieval   │      │
 │  2b narrative clustering + coordination  ✅  │      │
 │     ("narrative watch") → /narratives        │      │
 └─────────────┬───────────────────────────────┘      │
               ▼                                       ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Layer 3 · Analyst agent (pluggable LLM)                   │
 │  query → plan → retrieve(corpus + KG + cyber) → CITED brief│
 │  measured by the eval harness (citation/faithfulness/recall)│
 └─────────────┬────────────────────────────────────────────┘
               ▼
        FastAPI (hardened, read-only + 1 agent route)
               ▼
        React / TypeScript dashboard  ✅ workbench · narrative watch · collection
```

## Stack

Python 3.12 · SQLAlchemy 2.0 + Alembic + Postgres · pydantic-settings · httpx + tenacity +
Prefect (ingestion) · sentence-transformers + BM25 hybrid retrieval · LangGraph (multi-agent
deliberation) · pluggable LLM backends (Ollama / MLX / OpenAI-compatible / Anthropic, free by
default) · DSPy (prompt optimization) · MLX LoRA (self-distillation fine-tune) · FastAPI
(hardened for public deploy) · React 19 + TypeScript + Vite + TanStack Query (dashboard).
Mirrors Sentinel's stack and conventions so the two read as one body of work.
ruff + mypy (strict) + pytest gate every change.

## Quickstart

```bash
make env && conda activate argus && make install   # one-time
make up                                             # Postgres + migrations (Docker)
make ingest Q="South China Sea"                     # pull open-source reporting on a topic
make enrich                                         # entity/event extraction + Admiralty scoring
make brief Q="What happened in the South China Sea this week?"   # generate a cited brief
make eval                                           # score the agent on the gold set
make api          # read-only API + agent route on :8000
```

Everything works with **no API key** (deterministic fallback). For best results, run a local
model via Ollama (`ollama pull qwen2.5:14b`; `llama2` is too weak). To use Claude, set
`ARGUS_LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` — the `auto` mode never selects it.

## Project context

ARGUS is the fourth in a portfolio of from-scratch, honestly-evaluated systems
([sentinel](../sentinel), [time-forecasting](../time-forecasting),
[mlx-tiny-transformer](../mlx-tiny-transformer)), oriented toward Singapore's **Digital and
Intelligence Service (DIS)** mission space: cyber defence, all-source/digital intelligence, and
information defence.
