# Roadmap

Built honestly: a milestone is only ✅ when it runs and is tested. The agent spine (0–4) is
complete and the FastAPI layer (5a) is live; React dashboard, narrative watch, and cyber-fusion
bridge are the remaining work, with live deployment deferred to after those land. Deadline
anchor: a demonstrable MVP well before **~10 Aug 2026**.

| # | Milestone | Status |
|---|---|---|
| 0 | Repo scaffold, packaging, Docker Compose (Postgres), config, DB models, CI gate | ✅ done |
| 1 | Collection — GDELT DOC 2.0 (query-driven) + curated world/agency RSS ingesters → corpus | ✅ done |
| 2 | Analysis 2a — entity/event extraction + dedup, Admiralty source-reliability scoring, hybrid (BM25 + dense) retrieval | ✅ done |
| 3 | Analyst agent — **multi-agent ACH deliberation** (LangGraph): hypotheses → analyst ↔ red-team → adjudicator; free-by-default LLM (Ollama / deterministic), citation-resolvable **cited brief** | ✅ done |
| 4 | Eval harness — gold query set; retrieval recall/MRR, citation coverage, fabrication-caught, calibration-trap (deterministic) | ✅ done |
| 5a | FastAPI (`/brief` + read-only graph, hardened: rate-limit/concurrency/size-cap guards; `GET /model` observability) | ✅ done |
| 5b | React / TypeScript dashboard — query box, brief with inline citations + reliability badges, narrative-watch panel | ⬜ |
| 6 | Analysis 2b — narrative clustering + coordination detection ("narrative watch") + `/narratives` API | ✅ done |
| 7 | Cyber-fusion bridge — `query_cyber_graph` tool over Sentinel's read-only API | ⬜ |
| 8 | Polish — fuller `EVAL.md` (judge calibration, multi-seed, LLM-path numbers), demo video, blog post | ⬜ |
| 9 | **Live deployment** — deferred; will follow once 5b + one of {6, 7} land | ⬜ deferred |

**Recommended floor to ship:** milestones 0–5a are done. Next: 5b (dashboard) then **one of {6, 7}** to complete the fusion story. Live deployment follows that — it is not imminent.

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
