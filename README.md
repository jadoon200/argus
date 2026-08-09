# ARGUS

[![CI](https://github.com/jadoon200/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/jadoon200/argus/actions/workflows/ci.yml)

**Live demo:** https://argus-lrhu.onrender.com (baked corpus + deterministic briefs; run locally with Ollama for live multi-agent deliberation)

**All-source intelligence analyst workbench** — a deterministic supervisor gathers from
**Sky** (HORUS), **Ocean** (PHAROS), **Cyber** (SENTINEL), and the open-source information
environment, then a **multi-agent ACH deliberation panel** fuses the source-rated evidence
into cited intelligence briefs held to a measured evaluation bar.

> **Portfolio fusion point.** [HORUS](https://github.com/jadoon200/horus) supplies the **Sky**
> picture (ADS-B and GNSS interference), [PHAROS](https://github.com/jadoon200/pharos) supplies
> the **Ocean** picture (AIS maritime awareness), and
> [SENTINEL](https://github.com/jadoon200/sentinel) supplies the **Cyber** picture (network
> intrusions × ATT&CK × CTI). ARGUS is the supervisor and synthesis layer: it selectively
> queries those read-only systems alongside its own news corpus, preserving provenance and
> Admiralty ratings. [DELPHI](https://github.com/jadoon200/delphi) is the portfolio's fifth
> project and the one ARGUS does not consume — it decides capacity rather than detecting
> events.

> **Status:** the lean fusion supervisor, Sky/Ocean/Cyber-OSINT workers, ACH agent spine,
> API, overview/workbench dashboard, and narrative watch are complete (plus DSPy prompt
> optimization and MLX LoRA fine-tuning).
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
3. **Routes and gathers across domains** — a deterministic **fusion supervisor** classifies
   the question and wakes only the relevant mini-agents: **Sky/HORUS**, **Ocean/PHAROS**,
   **Cyber/SENTINEL**, and **OSINT**. Generic domain requests fuse OSINT with the matching
   sibling (`ocean overview` → OSINT + PHAROS); explicitly naming sources constrains the gather
   to exactly those systems (`from PHAROS` → PHAROS only). Broad domain synonyms keep relevant
   news in the fused side (`ocean` matches sea/maritime reporting), and thin OSINT coverage can
   trigger collect-on-demand. Workers make read-only HTTP calls, relevance-filter, collapse
   repeated same-source detector observations into one evidence episode, and return the existing
   rated `EvidenceItem` contract. Different sources remain separate as corroboration. They run
   no LLM; the expensive reasoning still happens once, which keeps peak memory to one local model
   on an M3 Pro.
   `ARGUS_FUSION_SUPERVISOR=false` restores the former flat broadcast for rollback.
4. **Deliberates a brief** — not a one-shot RAG summary. A **multi-agent panel** argues the
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
5. **Watches narratives and tags influence tactics** — clusters reporting into narratives,
   flags **coordination** (synchronized messaging) and **influence-operations techniques**
   (DISARM Red Framework: deepfakes, conspiracy narratives, flooding, etc.), both information-defence
   signals (surfaced at `GET /narratives`). Also detects **contested-event framing divergence**
   across sources, especially across reliability tiers, surfacing contradictions at `GET /contested`
   — all human-review signals, never automated verdicts.
6. **Closes the loop on collection** — a brief ends with gaps; the agent tasks the next
   collection by converting gaps into targeted open-source queries, ingests the results, and
   re-briefs on the expanded corpus (`make collect-loop`).
7. **Shows its work before synthesis** — `GET /overview` returns cached status, counts, and
   the latest item for all four lanes; `POST /fusion/preview` exposes the supervisor decision,
   per-lane counts, and fused evidence without an LLM. Every fresh brief also reports
   `lanes_consulted` and the routing reason. A named cyber actor still resolves to its contested
   open-reporting nation attribution (`APT28 ⇄ Russia`; `GET /actors`).
8. **Speaks the standard** — exports the DISARM-keyed influence-ops graph as a conformant
   **STIX 2.1** bundle (`GET /stix`: techniques → `attack-pattern`, narratives → `report`,
   sources → `identity`), ingestible by OpenCTI / MISP / the ATT&CK Navigator and joinable with
   Sentinel's ATT&CK STIX in one object model — cyber + cognitive on the same standard.

## Why it's built this way

- **Honest evaluation, not a demo.** The agent is *measured*: retrieval recall, **citation
  accuracy** (does each cited source actually exist and support the claim?), **faithfulness**
  (no ungrounded claims), and source-reliability calibration — with recorded **negatives**
  where it fails. **Faithfulness and citation-support metrics are now measured** via an
  LLM-as-judge (free/local Ollama) **and cross-checked by a deterministic NLI scorer** (`ARGUS_NLI_ENABLED`, opt-in): a cross-encoder entailment model that provides stable, independent verification alongside the LLM judge. **Confidence is self-consistently calibrated** (opt-in high-assurance
  mode via `ARGUS_ASSURANCE_SAMPLES`): the adjudicator is sampled K times and confidence is
  downgraded if the samples don't mostly agree, honest calibration over a lucky single draw.
  This eval harness is the point; a RAG demo that nobody graded isn't an intelligence tool.
  See [`docs/EVAL.md`](docs/EVAL.md).
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
                         analyst question
                                │
                  deterministic fusion supervisor
                     route + explain (no model)
          ┌─────────────┬─────────────┬─────────────┐
          ▼             ▼             ▼             ▼
     OSINT worker   Sky / HORUS   Ocean / PHAROS  Cyber / SENTINEL
     corpus + GDELT  ADS-B + GNSS     AIS GEOINT       ATT&CK + CTI
          └─────────────┴─────────────┴─────────────┘
                                │
                    fused list[EvidenceItem]
                     ratings + provenance intact
                                │
                quick synthesis OR ACH deliberation
              hypotheses → score → analyst ⇄ red team
                         → adjudicator
                                │
                   cited, calibrated intelligence brief
                                │
        FastAPI → overview · workbench · narratives · collection
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

# Exercise the live read-only Sky/Ocean/Cyber workers through the supervisor:
make fusion-demo Q="Assess suspicious vessels in the Singapore Strait"
```

For persistent local fusion settings, copy [`.env.example`](.env.example) to `.env`. The
checked example points at the portfolio's live read-only sibling APIs; replace them with local
URLs when running the four services together.

Everything works with **no API key** (deterministic fallback). For best results, run a local
model via Ollama (`ollama pull qwen2.5:14b`; `llama2` is too weak). To use Claude, set
`ARGUS_LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` — the `auto` mode never selects it.

## Project context

ARGUS is one of five from-scratch, honestly-evaluated systems built as one body of work —
[SENTINEL](https://github.com/jadoon200/sentinel) (cyber),
[HORUS](https://github.com/jadoon200/horus) (air),
[PHAROS](https://github.com/jadoon200/pharos) (maritime),
[DELPHI](https://github.com/jadoon200/delphi) (infrastructure capacity) and this one
(all-source fusion) — alongside smaller model-craft work such as
[mlx-tiny-transformer](https://github.com/jadoon200/mlx-tiny-transformer). The common thread
is the evaluation discipline rather than the domain: measured baselines, pre-registered
questions, and negatives written down where they fell.
