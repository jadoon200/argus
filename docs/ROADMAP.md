# Roadmap

Built honestly: a milestone is only ✅ when it runs and is tested. The agent spine (0–4), the
FastAPI layer (5a), the React dashboard (5b), narrative watch (6), and the cyber-fusion bridge
(7) are all complete; what remains is polish (8) and the deferred live deployment (9).
Deadline anchor: a demonstrable MVP well before **~10 Aug 2026**.

| # | Milestone | Status |
|---|---|---|
| 0 | Repo scaffold, packaging, Docker Compose (Postgres), config, DB models, CI gate | ✅ done |
| 1 | Collection — GDELT DOC 2.0 (query-driven) + curated world/agency RSS ingesters → corpus | ✅ done |
| 2 | Analysis 2a — entity/event extraction + dedup, Admiralty source-reliability scoring, hybrid (BM25 + dense) retrieval | ✅ done |
| 3 | Analyst agent — **multi-agent ACH deliberation** (LangGraph): hypotheses → analyst ↔ red-team → adjudicator; free-by-default LLM (Ollama / deterministic), citation-resolvable **cited brief** | ✅ done |
| 4 | Eval harness — gold query set; retrieval recall/MRR, citation coverage, fabrication-caught, calibration-trap (deterministic) | ✅ done |
| 5a | FastAPI (`/brief` + read-only graph, hardened: rate-limit/concurrency/size-cap guards; `GET /model` observability) | ✅ done |
| 5b | React / TypeScript dashboard — workbench (query → rated evidence + cited brief with Admiralty badges), narrative-watch panel, collection (corpus/source-reliability/backend) | ✅ done |
| 6 | Analysis 2b — narrative clustering + coordination detection ("narrative watch") + `/narratives` API | ✅ done |
| 7 | Cyber-fusion bridge — SENTINEL cyber campaigns as citable evidence (read-only, `ARGUS_SENTINEL_API_URL`) | ✅ done |
| 8 | Polish — fuller `EVAL.md` (judge calibration, multi-seed, LLM-path numbers), demo video, blog post | ⬜ |
| 9 | **Live deployment** — deferred; the dashboard (5b) has landed, so this is the next major step when chosen | ⬜ deferred |

Beyond the numbered spine, the "tune to our purpose" track is also done: domain-specialized
agent personas (Key Assumptions Check + Indicators & Warnings), **DSPy** prompt optimization
(`make optimize`, `src/argus/optimize/`), free **MLX** + OpenAI-compatible LLM backends, and
**MLX LoRA self-distillation** (`make finetune`, `src/argus/finetune/`, see `docs/FINETUNE.md`).

**Post-MVP innovations** (landed after milestones 0–7): **contested-event detection**
(`src/argus/nlp/contest.py`, `/contested` endpoint) — measures framing divergence across sources
within events, especially across reliability tiers; deterministic, no LLM. **Self-consistency
confidence calibration** (`ARGUS_ASSURANCE_SAMPLES`, `src/argus/agent/assurance.py`) — samples
the adjudicator K times and derives confidence from agreement, honest calibration over a lucky draw.
**Citation precision** — adjudicator prompt tightened to cite only *directly* supporting items,
targeting LLM-judge citation-support. **Closing-the-loop collection** (`make collect-loop`,
`src/argus/collection/{tasking,loop}.py`) — turns a brief's intelligence gaps into the next search
queries, ingests + enriches, then re-briefs on the expanded corpus.

**Recommended floor to ship:** milestones 0–7 are done — the full open-source + cyber-fusion
story runs end-to-end today, with the React dashboard on top. What's left is polish (8) and the
deferred live deployment (9) — neither imminent.

## Design decisions already locked

- **Zero-cost / runs-offline.** Free sources (GDELT, RSS) and free/local models only; the LLM
  layer is pluggable with a deterministic extractive fallback so the product and CI run with
  no key. (Mirrors Sentinel.)
- **Honest evaluation over demos.** No agent claim ships without a measured number and recorded
  negatives in `docs/EVAL.md`.
- **Source-rated + cited.** NATO Admiralty (source A–F × credibility 1–6); every brief claim
  carries an inline citation to a real ingested document.
- **Responsible use.** Public/open-source data only, defensive/analytical only, no individual
  targeting, no auth-gated scraping; coordination signals are human-review decision support.

## Open questions (resolve as we build)

- NER backend: spaCy `en_core_web_sm` (free, simple) vs GLiNER (better, heavier) — benchmark on
  a small labelled slice before locking, the Sentinel way.
- Event dedup threshold + clustering algorithm (embedding cosine + time window) — tune against a
  hand-labelled dedup set, record the operating point.
- Coordination detection method (co-posting time-bursts vs shared-phrasing graphs) — start
  simple (time-bucketed co-occurrence), validate on a public CIB dataset, keep the negative.
