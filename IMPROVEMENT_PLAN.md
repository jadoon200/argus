# Cross-Project Bug Sweep & Improvement Plan (ARGUS + SENTINEL)

Date: 2026-07-19. Scope: full bug audit of both sibling projects, fixes for confirmed
bugs, then a prioritized improvement backlog. Branches: ARGUS `fix/bug-sweep-improvements`
(off `main`), SENTINEL `fix/bug-sweep-improvements` (off `feat/cloud-deploy`, which is even
with `main`).

Audit method: independent per-repo code audits + full test-suite baselines. Both suites
were green before any change (ARGUS 189 passed / 1 skipped; SENTINEL 104 passed, 84% cov).

---

## ARGUS

### Bugs (confirmed)

- [x] **A1 — Assurance mode silently downgrades confidence to "low" when every resample
  fails.** `agent/assurance.py` `assured_confidence()` called `calibrate([])` → `("low",
  0.0)` when all K adjudicator resamples failed to parse (timeout/malformed JSON — a
  recorded real failure mode), and `analyst.py` overwrote the primary panel's confidence
  with it. Opposite of the documented "never worse than one-shot" contract.
  **Fixed:** returns `None` when no resample parses; caller keeps the primary confidence
  and logs `assurance_unavailable_keeping_primary`. Regression test added
  (`test_assured_confidence_all_resamples_fail_keeps_primary`).

- [x] **A2 — Relevance gate falsely blocks subject-less conversational follow-ups.**
  `agent/triage.py` `relevant_count()` returned 0 when the query had no subject tokens
  ("Any updates?", "What's the latest on this?"), so `generate_brief` discarded perfectly
  relevant retrieved evidence and answered "No relevant reporting available — collect
  first". Breaks the Workbench's conversational-analyst design for multi-turn follow-ups.
  **Fixed:** subject-less queries treat relevance as unknowable → count all evidence
  (pass-through; empty evidence still gates). Also made the `_GENERIC` check
  plural-tolerant (`updates` ≡ `update`) via `_is_generic()`. Tests updated + extended.

- Gate after fixes: `make check` green — ruff, ruff-format, mypy strict, **190 passed / 1 skipped**.

### Improvements (backlog, prioritized)

- [x] **A3 — Reuse the process-wide `default_mapper()` in `narrative/run.py refresh()`.**
  It constructs a fresh `DisarmMapper()` on every on-demand collection (`/ingest` and
  auto-collected `/brief` — user-facing request path), re-embedding the DISARM catalog
  each time. `nlp/disarm.py default_mapper()` exists precisely to cache this. **Done:**
  `refresh()` now calls `default_mapper()`; catalog embeds once per process.
- [x] **A4 — Thread-safety tests for `api/limits.py`.** **Done:** `tests/test_limits.py`
  hammers `RateLimiter.allow()` from 16 threads (exact-budget admission, per-client
  isolation) and proves the `ConcurrencyLimiter` cap with 3 provably-simultaneous slot
  holders + deterministic full→`SlotUnavailable` behavior.
- [x] **A5 — Bound the SENTINEL bridge fetch.** SENTINEL ignores the `limit` param and
  returns every campaign, so the query path's `limit * 10` pool was unbounded upstream.
  **Done:** `campaigns()` truncates client-side to the requested pool size; test drives a
  500-row upstream through a 30-row cap.

## SENTINEL

### Bugs (confirmed)

- [x] **S1 — Every `ti ti-*` icon in the dashboard renders as empty space.** ~25 uses of
  Tabler-icon markup across `ThreatFeed.tsx`, `Landscape.tsx`, `ReportCard.tsx`, but no
  `@tabler/icons-webfont` dependency, no CDN link, no `.ti` / `@font-face` CSS anywhere
  (verified in the built `dist/`). Ships broken in the live cloud-deploy image.
  **Fixed:** added `@tabler/icons-webfont` dependency, imported its CSS in `main.tsx`,
  rebuilt `dist/` (webfont present in bundle), CI grep-guard not added (see S3).

### Likely bugs / deploy hardening

- [x] **S2 — Per-client rate limiter collapses to one global bucket on Render.**
  `_client_key` uses the TCP peer (always the Render LB) unless
  `SENTINEL_API_TRUST_FORWARDED_HEADER=true`; `render.yaml` never sets it. One busy
  visitor could 429 everyone once the OSINT bridge is enabled. **Fixed:** set the env var
  in `render.yaml` (Render's edge controls `X-Forwarded-For`, safe to trust) + DEPLOY.md
  callout.

### Improvements (backlog, prioritized)

- [x] **S3 — CI guard for the icon regression.** **Done:** the frontend CI job now fails
  if the Tabler icon-font CSS/woff2 ever falls out of the built bundle again (guard
  verified against the local build). A real component smoke test remains a nice-to-have.
- [x] **S4 — `tag_report()` sliced to `max_techniques` before applying `min_score`.**
  Confirmed real: aggregation ranks by `(corroborations, score)`, so a strong
  single-corroboration technique could be pushed out of the cap by floor-failing entries
  and dropped entirely. **Fixed:** floor first, then cap; regression test added.
- [x] **S5 — `keepwarm.yml` hardcoded fallback URL.** **Verified non-issue (recorded
  negative):** `curl -fsS` fails the workflow run (red X + notification) if the URL dies,
  so it is not a silent no-op. No change made.
- [ ] **S6 — IDS coverage** — `ids/beacon.py` / `spectral.py` at ~48% test coverage while
  feeding the seed-data pipeline every cloud visitor sees.

---

## Progress log

- 2026-07-19: Audits complete (both baselines green). A1, A2 fixed + tested in ARGUS,
  full gate green. Plan created.
- 2026-07-19: A3 done (mapper reuse). S1 (icon webfont) and S2 (Render trust-forwarded
  header) fixed in SENTINEL on `fix/bug-sweep-improvements`; `make check` + frontend
  build green, dist rebuilt (webfont verified in bundle; browser screenshot not possible
  in this session — origin approval unavailable).
- 2026-07-19 (cont.): S3 (CI icon guard, verified locally), S4 (floor-before-cap fix +
  test, SENTINEL 105 passed) committed. S5 investigated → non-issue, recorded. A4
  (limiter concurrency tests) + A5 (bridge pool cap) committed; ARGUS gate green at
  195 passed / 1 skipped.

## Remaining

- **S6** (SENTINEL: raise `ids/beacon.py` / `ids/spectral.py` coverage from ~48%) — the
  only open item; delegated to a subagent at end of session, see log/PR state for outcome.
- Both branches: `fix/bug-sweep-improvements` in each repo. ARGUS branched off `main`;
  SENTINEL off `feat/cloud-deploy` (== `main` at branch time). Open PRs when ready.
