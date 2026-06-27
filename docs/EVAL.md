# Evaluation

> The point of ARGUS is not that it *produces* briefs — anything with an LLM can produce a
> brief. The point is that the briefs are **measured**: grounded in real sources, correctly
> cited, and honest about confidence. This document defines the bar and records every result,
> including the failures. Numbers fill in as milestones land (see `docs/ROADMAP.md`);
> placeholders are marked `TBD`.

## What we measure

### 1. Retrieval quality (Layer 2a)
Given a labelled query → relevant-documents set, score the hybrid (BM25 + dense, RRF) retriever.

| Metric | Definition | Result |
|---|---|---|
| Recall@10 | fraction of relevant docs in the top 10 | TBD |
| Recall@20 | fraction of relevant docs in the top 20 | TBD |
| MRR | mean reciprocal rank of the first relevant doc | TBD |
| Dense vs BM25 vs RRF | ablation — does fusion actually beat either alone? | TBD |

### 2. Citation accuracy (the headline)
Every claim in a brief carries a citation `[doc_id]`. We check, per cited claim:

- **Resolvable** — does `doc_id` exist in the corpus? (A fabricated citation is the worst
  failure mode; target **100%** resolvable, enforced in code, not just measured.)
- **Supporting** — does the cited document actually support the claim? (LLM-as-judge with a
  cheap/local judge, spot-checked against a human-labelled subset.)

| Metric | Definition | Result |
|---|---|---|
| Citation resolvable rate | cited `doc_id`s that exist | TBD (hard target 100%) |
| Citation support rate | cited docs that support their claim | TBD |
| Judge–human agreement | judge vs human labels on the support call | TBD |

### 3. Faithfulness / groundedness
Fraction of brief claims that are supported by *some* retrieved document (no free-floating
assertions). Hallucinated-claim rate is the inverse and is reported directly.

| Metric | Result |
|---|---|
| Grounded-claim rate | TBD |
| Hallucinated-claim rate | TBD |

### 4. Source-reliability calibration
Does the Admiralty rating mean anything? We check that higher-rated sources are, empirically,
less often contradicted by later corroborated reporting — i.e. the rating has predictive
content, not just a label.

| Metric | Result |
|---|---|
| Reliability ↔ later-contradiction correlation | TBD |

### 5. Backend parity
The deterministic fallback and the Claude-backed agent are scored on the **same** gold set, so
the cost of running key-free is explicit and honest.

| Backend | Citation support | Faithfulness | Notes |
|---|---|---|---|
| deterministic (extractive) | TBD | TBD | always-on floor; no key |
| local (Ollama / MLX) | TBD | TBD | |
| Claude (Anthropic API) | TBD | TBD | best quality, optional |

## Gold set

A small, hand-curated set of analyst queries with: relevant-document labels, a set of claims a
correct brief should make, and known traps (topics with thin/low-reliability sourcing where the
*right* answer is low confidence + an explicit intelligence gap). Lives under
`src/argus/eval/`. Kept deliberately small and honest rather than large and noisy.

## Harness status

`make eval` (`argus.eval.run`) scores a fixture gold set (`src/argus/eval/goldset.py`).
Retrieval metrics are deterministic (LLM-free, CI-safe); brief metrics use whatever backend
is available (local Ollama, else the template digest).

**Deterministic baseline (template backend, fixture corpus):** mean recall@3 1.00, mean MRR
1.00, citation coverage 1.00, fabrication attempts caught 0, calibration-trap breaches 0. The
fixture corpus is small and lexically clean, so retrieval=1.00 mainly guards against
regressions — the discriminating checks are citation coverage, fabrication, and the trap.

**LLM-path numbers (a deliberated brief vs the digest): pending** a capable local model
(`qwen2.5:14b`); they land here once measured.

## Recorded negatives (where it fails)

The honest half. To be filled as found — e.g. thin-source topics where the agent overstates
confidence, non-English reporting it under-retrieves, coordination false positives on organic
viral events. Each negative gets characterized (why it fails, when), not hidden.

- **Template digest is not calibration-aware** — it is a relevance-ranked evidence digest, so
  it always reports *low* confidence and makes no analytic judgment. Honest by construction
  (it never overstates), but it is not a substitute for the deliberated brief.
- _More land once the LLM-path eval runs on `qwen2.5:14b`._
