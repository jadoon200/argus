# Roadmap

Built honestly: a milestone is only ✅ when it runs and is tested. Today the repo is at
**scaffold**; the MVP spine (steps 1–5) is the floor to ship, with the two fusion layers
(6–7) as the extensions that make it "all-source," and polish (8) last. Deadline anchor: a
demonstrable, deployed MVP well before **~10 Aug 2026**.

| # | Milestone | Status |
|---|---|---|
| 0 | Repo scaffold, packaging, Docker Compose (Postgres), config, DB models, CI gate | ✅ done |
| 1 | Collection — GDELT DOC 2.0 (query-driven) + curated world/agency RSS ingesters → corpus | ✅ done |
| 2 | Analysis 2a — entity/event extraction + dedup, Admiralty source-reliability scoring, hybrid (BM25 + dense) retrieval | ✅ done |
| 3 | Analyst agent — **multi-agent ACH deliberation** (LangGraph): hypotheses → analyst ↔ red-team → adjudicator; free-by-default LLM (Ollama / deterministic), citation-resolvable **cited brief** | ✅ done |
| 4 | Eval harness — gold query set; retrieval recall/MRR, citation coverage, fabrication-caught, calibration-trap (deterministic) | ✅ done |
| 5 | FastAPI (`/brief` + read-only graph, hardened) + React dashboard; **deploy live** | ⬜ |
| 6 | Analysis 2b — narrative clustering + coordination detection ("narrative watch" panel) | ⬜ |
| 7 | Cyber-fusion bridge — `query_cyber_graph` tool over Sentinel's read-only API | ⬜ |
| 8 | Polish — `MODEL_CARD.md`, fuller `EVAL.md` (judge calibration, multi-seed), demo video, blog post | ⬜ |

**Recommended floor to ship:** steps 0–5 **+ one of {6, 7}**. Ship the agent spine first; treat
the narrative watch and the cyber bridge as the two extensions that complete the fusion story,
not prerequisites.

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
