# Model card — ARGUS analyst agent

> Seed card. Sections marked `TBD` fill in as the system reaches MVP. The point of writing it
> now is that the *intended* use, limits, and failure modes are committed before the results
> are, so the evaluation can't quietly move the goalposts.

## Overview

ARGUS is an **all-source open-source-intelligence (OSINT) analysis aid**. Its central artifact
is a **cited intelligence brief**: given an analyst query, a tool-using agent retrieves over a
corpus of open-source reporting (GDELT global news + curated RSS) and composes a structured
assessment — key judgments, evidence with source-reliability ratings, a timeline, a confidence
call, and intelligence gaps — with every claim cited to a real ingested document.

It is **decision support for a human analyst**, not an autonomous decision-maker.

## Intended use

- Help an analyst triage and summarize **public, open-source** reporting on a topic, with
  provenance and source-reliability made explicit.
- Surface corroboration, contradictions, timelines, and candidate coordinated-narrative
  patterns for **human review**.

## Out-of-scope / prohibited use

- **No targeting or profiling of individuals**; no auth-gated or private data; no scraping
  behind logins.
- **Not an automated verdict.** Coordination/narrative flags are statistical signals on public
  posting patterns, for a human to adjudicate — never an automated "this is disinformation" or
  "this account is hostile" determination.
- Not a substitute for classified/all-source collection; it sees only what is openly published.

## Data

- **GDELT DOC 2.0 API** — global news index, free, no key. Public news metadata + snippets.
- **Curated world/agency RSS** — wire services, broadcasters, government advisories; each tagged
  with its publisher for provenance.
- Coverage and language skew (English-heavy) are real limitations — see Limitations.

## Source-reliability model

NATO **Admiralty System**: source reliability (A completely reliable … F cannot be judged) ×
information credibility (1 confirmed … 6 cannot be judged). Source reliability comes from a
curated, transparent per-source map; per-document credibility is derived from corroboration
across independent sources. The rating is shown, never hidden, and its predictive value is
itself evaluated (`docs/EVAL.md` §4).

## LLM backends

Pluggable: deterministic extractive briefer (always-on, no key), local (Ollama / Apple MLX),
or Claude (Anthropic API, best quality, optional). All are scored on the same gold set so the
key-free floor is explicit.

## Evaluation

Full methodology and results in [`docs/EVAL.md`](EVAL.md): retrieval recall, **citation
accuracy** (resolvable + supporting), faithfulness/groundedness, source-reliability calibration,
and cross-backend parity — with recorded negatives. Headline numbers: **TBD**.

## Limitations & failure modes (committed up front)

- **Language/coverage skew** — English-language, well-indexed sources dominate; under-reported
  regions and non-English reporting are under-retrieved.
- **Open-source ceiling** — only sees public reporting; absence of evidence ≠ evidence of
  absence.
- **Confidence on thin sourcing** — the known trap; the eval gold set deliberately includes
  thin-source topics to check the agent says "low confidence + intelligence gap" rather than
  overstating. Result: TBD.
- **Coordination false positives** — organic viral events can look coordinated; flagged as
  human-review signal only.

## Responsible use

Defensive/analytical, public data only. See README → *Responsible use* and CLAUDE.md →
*Conventions*.
