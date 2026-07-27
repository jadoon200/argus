# Roadmap

Built honestly: a milestone is only ✅ when it runs and is tested. The agent spine (0–4), the
FastAPI + React layers (5), narrative watch (6), cyber bridge (7), **Sky/Ocean/Cyber-OSINT
supervisor fusion (7b)**, and the Render deployment (9) are complete; what remains is polish (8).
Deadline anchor: a demonstrable MVP well before **~10 Aug 2026**.

| # | Milestone | Status |
|---|---|---|
| 0 | Repo scaffold, packaging, Docker Compose (Postgres), config, DB models, CI gate | ✅ done |
| 1 | Collection — GDELT DOC 2.0 (query-driven) + curated world/agency RSS ingesters → corpus | ✅ done |
| 2 | Analysis 2a — entity/event extraction + dedup, Admiralty source-reliability scoring, hybrid (BM25 + dense) retrieval | ✅ done |
| 3 | Analyst agent — **multi-agent ACH deliberation** (LangGraph): hypotheses → analyst ↔ red-team → adjudicator; free-by-default LLM (Ollama / deterministic), citation-resolvable **cited brief** | ✅ done |
| 4 | Eval harness — gold query set; retrieval recall/MRR, citation coverage, fabrication-caught, calibration-trap (deterministic) | ✅ done |
| 5a | FastAPI (`/brief` + read-only graph, hardened: rate-limit/concurrency/size-cap guards; `GET /model` observability) | ✅ done |
| 5b | React / TypeScript dashboard — fusion overview + gather preview, workbench (query → rated evidence + cited brief with Admiralty badges), narrative-watch panel, collection | ✅ done |
| 6 | Analysis 2b — narrative clustering + coordination detection ("narrative watch") + `/narratives` API | ✅ done |
| 7 | Cyber-fusion bridge — SENTINEL cyber campaigns as citable evidence (read-only, `ARGUS_SENTINEL_API_URL`) | ✅ done |
| 7b | **Lean multi-agent source fusion** — deterministic supervisor fuses OSINT + domain lanes for generic requests and honors explicit named-source scope; one central synthesis; transparent `lanes_consulted`; cached `/overview` | ✅ done |
| 8 | Polish — fuller `EVAL.md` (judge calibration, multi-seed, LLM-path numbers); demo video / blog post dropped, the dashboard's explainer carries the story | ⬜ |
| 9 | **Live deployment** — one-service Render app; live sibling URLs wired read-only; health/evidence paths smoke-tested | ✅ done |

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
queries, ingests + enriches, then re-briefs on the expanded corpus. **DISARM influence-ops tagging**
(`src/argus/nlp/disarm.py`, `Narrative.disarm` column, `GET /disarm/techniques`, `POST /map-disarm`) —
zero-shot bi-encoder mapping of narratives to DISARM Red Framework techniques (20 across Plan/Prepare/Execute/Assess:
deepfakes, conspiracy narratives, information flooding, etc.); mirrors SENTINEL's ATT&CK mapper;
advisory human-review signal only, never an automated verdict. **Deterministic NLI faithfulness/citation cross-check**
(`src/argus/eval/nli.py`, `ARGUS_NLI_ENABLED`, opt-in) — a cross-encoder NLI model (`cross-encoder/nli-deberta-v3-base`)
that scores claim–evidence entailment deterministically and independently, free from the LLM judge's run-to-run variance
and self-judging bias; measured agreement on a labelled 10-pair slice (NLI 0.90 vs LLM judge 1.00); its value is
stability and independence, not per-item accuracy — ships as a deterministic cross-check reported alongside the LLM judge.
(NLI faithfulness now uses **atomic claim decomposition** — `decompose()` splits each judgment into atomic sub-claims so
faithfulness is the RAGAS-style fraction entailed, fixing strict entailment's collapse on analytic writing.) **STIX 2.1 export**
(`src/argus/stix.py`, `GET /stix`) — serializes the DISARM-keyed influence-ops graph (DISARM techniques → `attack-pattern`,
tagged narratives → `report`, sources → `identity`) as a conformant, deterministic STIX 2.1 bundle, ingestible by
OpenCTI / MISP / the ATT&CK Navigator and joinable with SENTINEL's ATT&CK STIX in one object model. Dependency-free.
**Cross-graph actor resolution** (`src/argus/actors.py`, `GET /actors`) — a curated threat-actor→nation registry
(~16 groups + vendor aliases) that resolves a threat group named in a SENTINEL cyber campaign to its widely-reported
nation attribution (`APT28 ⇄ Russia`), annotated onto the cyber-fusion evidence so the cyber lane joins the geopolitical
actor of the brief; attribution shown as contested, open-reporting consensus, human-review — never an automated verdict.

**Multi-domain source-agent fusion** (`src/argus/agent/{supervisor,workers}.py`) promotes the
existing bridges into first-class workers. A lexical, deterministic supervisor fuses OSINT with
the matching Sky, Ocean, or Cyber lanes for generic domain requests, while an explicitly named
system constrains the gather to exactly the named source or sources. Subject-less and explicit
all-source requests conservatively fan out. Workers gather in the shared `EvidenceItem` contract,
preserve Admiralty ratings, collapse repeated same-source detector observations into unique
evidence episodes, and reject least-irrelevant OSINT filler before presentation, while the
existing quick/ACH paths remain the only synthesis brain. This avoids loading multiple models on
the M3 Pro. The old flat broadcast remains available via `ARGUS_FUSION_SUPERVISOR=false`.
`/overview` caches server-side health/count/last-item fan-out; `/fusion/preview` makes routing and
gathered evidence visible without an LLM.

**Recommended floor to ship:** milestones 0–7b and 9 are done — the full OSINT + Sky + Ocean +
Cyber fusion story runs end-to-end through the supervisor and React dashboard. What remains is
portfolio polish (8), not a missing product path.

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
