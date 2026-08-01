# Evaluation

> The point of ARGUS is not that it *produces* briefs — anything with an LLM can produce a
> brief. The point is that the briefs are **measured**: grounded in real sources, correctly
> cited, and honest about confidence. This document defines the bar and records every result,
> including the failures. Numbers fill in as milestones land (see `docs/ROADMAP.md`);
> placeholders are marked `TBD`.

## What we measure

### 1. Retrieval quality (Layer 2a)
Given a labelled query → relevant-documents set, score the retriever. Measured by
`scripts/eval_retrieval.py` over the gold set (**20 documents, 10 labelled queries**),
run locally where the full embedding model is present.

| Ranker | R@1 | R@3 | R@5 | MRR |
|---|---|---|---|---|
| BM25 only | 0.750 | 1.000 | 1.000 | 1.000 |
| Dense only | 0.750 | 1.000 | 1.000 | 1.000 |
| RRF hybrid | 0.750 | 1.000 | 1.000 | 1.000 |

**The ablation is unanswered, and the reason is the fixture, not the retriever.** All three
rankers score identically, because BM25 alone already places a relevant document at rank 1
for all 10 queries — the gold queries are lexically distinctive enough that there is no
headroom for the dense channel or the fusion to demonstrate anything. So this table records
that the retriever clears the gold set, and *nothing* about whether hybrid retrieval beats
either half. Publishing "RRF = 1.000" as evidence for fusion would be reading a saturated
benchmark as a result.

`Recall@10` and `Recall@20` were the originally-stated metrics and have been dropped as
uninformative here: with a 20-document corpus, R@20 is 1.0 by construction and R@10 only
asks whether a relevant document reached the top half. R@1/R@3 are what the fixture was
designed to stress ("the corpus is large enough that recall@3 can fail").

Answering the ablation needs a harder labelled set — more documents, and distractors that
are *lexically* close to the queries but not relevant, which is where a dense channel should
earn its place. That set does not exist yet; inventing distractors to produce a favourable
separation would be fabricating the result this table exists to prevent.

### 2. Citation accuracy (the headline)
Every claim in a brief carries a citation `[doc_id]`. We check, per cited claim:

- **Resolvable** — does `doc_id` exist in the corpus? A fabricated citation is the worst
  failure mode, so this is **enforced in code, not just measured**: every citation resolves
  through `_resolve_citations`/`_resolve_label` and anything unresolvable is dropped (and the
  attempt counted). The eval's "fabrication attempts caught" number is the audit of that.
  Free-text citation parsing now stricter: a bare number inside prose (e.g. `[2 vessels]`)
  resolves as a label only in a *pure* citation list (every token is a label/number/doc-id);
  otherwise it cites nothing.
- **Supporting** — does the cited item actually support the claim? Implemented as an
  **LLM-as-judge** (`argus/eval/judge.py`): a strict judge reads each key judgment against the
  evidence and returns a structured `{grounded, supported}` verdict. Free/local (the same
  Ollama backend); runs only when a backend is available (the deterministic eval stays LLM-free
  and CI-safe). Numbers are auto-recorded below when `make eval` runs with a model.

| Metric | Definition | Result |
|---|---|---|
| Citation resolvable rate | cited `doc_id`s that exist | **100% (enforced)** |
| Citation support rate | cited items that support their claim | see auto-recorded block |
| Judge–human agreement | judge vs human labels on the support call | **0.90 (9/10)** — see caveat |

The agreement figure is the cross-family NLI scorer against the hand-labelled entailment
slice (`ENTAILMENT_GOLD`, 5 entailed / 5 not). **Read it as a spot-check, not an estimate:**
at n=10 the 95% interval runs roughly 0.60–0.98, so it rules out a scorer that is badly
broken and rules in very little else.

### 3. Faithfulness / groundedness
Fraction of key judgments the LLM-judge finds **grounded** in *some* evidence item (no
free-floating assertions); the hallucinated-claim rate is the inverse. Measured by the same
`judge_brief`; recorded in the auto block below.

> **Self-judging caveat — now measured, and it is large.** With a local model the judge and
> the analyst are the same family. Scoring the *same* Ollama briefs both ways: the LLM judge
> reports faithfulness **0.90**, the cross-family NLI scorer **0.383** — the model grading its
> own output is **2.4× more generous**. Treat any self-judged number as a regression signal
> only; the cross-family column is the one to read.

### 4. Source-reliability calibration
Does the Admiralty rating mean anything? We check that higher-rated sources are, empirically,
less often contradicted by later corroborated reporting — i.e. the rating has predictive
content, not just a label.

| Metric | Result |
|---|---|
| Reliability ↔ later-contradiction correlation | TBD |

### 5. Fusion lane routing

The source-domain supervisor is deterministic, so it has its own labelled set independent of
brief quality. `src/argus/eval/fusion.py` covers eleven query shapes: generic Ocean, Sky, Cyber,
a Sky+Ocean hybrid, OSINT-only politics, a subject-less follow-up that must conservatively fan
out, four explicitly scoped source requests, and a two-source PHAROS+SENTINEL comparison. We
measure micro precision/recall over lane labels plus exact-set match per query.

| Metric | Result |
|---|---|
| Lane-selection precision | **1.00 (11-query labelled v2 set)** |
| Lane-selection recall | **1.00 (11-query labelled v2 set)** |
| Exact lane-set match | **1.00 (11/11)** |

This is a deliberately small regression set, not proof of open-domain semantic routing. It is
executable (`evaluate_routing()`), included in `make eval`, and paired with mocked integration
tests proving a generic Ocean query wakes OSINT+Ocean, `from PHAROS` wakes only Ocean, and the
same contract holds for HORUS, SENTINEL, and explicit OSINT. The rollback flag
(`ARGUS_FUSION_SUPERVISOR=false`) is also tested to consult all lanes and de-duplicate their
evidence.

Broad domain wording uses small deterministic synonym sets at the evidence gate (`ocean` ↔
sea/maritime, `sky` ↔ air/aviation, `cyber` ↔ CTI vocabulary), so the OSINT side of a generic
domain request is not discarded merely because the reporting uses a domain synonym. When a
generic fused brief has thin OSINT coverage, collect-on-demand is still tasked even if the
sibling already returned several incidents; an explicitly source-scoped sibling request skips
OSINT collection entirely. A lane can still honestly return zero items when no matching public
reporting exists—source scoping controls which workers are consulted, never fabricates evidence.

**Live source-path smoke (2026-07-26):** all three sibling `/health` endpoints returned OK;
PHAROS `/stats` reported 7 Ocean incidents and returned citable `/geoint/evidence`; HORUS
reported 10 Sky incidents and returned citable `/geoint/evidence`; SENTINEL reported 2 Cyber
campaigns. This verifies the read-only source APIs and contracts. The mocked suite remains the
repeatable gate because live free-tier services can sleep or change data.

The same smoke ran through a seeded local ARGUS API and React dashboard against those live
siblings. Ocean-, Sky-, and Cyber-shaped questions each selected only OSINT plus the expected
domain lane; the deterministic brief path interleaved the sibling results with OSINT and cited
their absolute source links. The browser pass also verified the four ready overview cards,
pre-synthesis gather preview, Admiralty badges, and visible lane-routing rationale.

**Evidence-uniqueness regression (2026-07-26):** the live source-path audit found that PHAROS
correctly emitted two detector observations five minutes apart for MMSI `563000029`, but ARGUS
treated their distinct upstream IDs as two analyst evidence cards. HORUS likewise emitted three
successive area-level GNSS observations for one corridor, and PHAROS represented one rendezvous
as reciprocal `A→B` and `B→A` rows. The presentation/synthesis boundary now collapses
same-source, same-subject detector observations inside a 30-minute episode window, keeps the
richest representative, and backfills with the next genuinely distinct incident. The general
evidence boundary also collapses exact IDs and same-source normalized-title episodes before
fusion, deliberation, evaluation, optimization, and fine-tuning. Different sources remain
separate because corroboration is diagnostic; different detector signals and later episodes
also remain separate. On the audited live payloads, PHAROS went from **7 raw rows to 5 unique
episodes** and HORUS from **10 to 8**. Mocked regressions cover the MMSI case, reciprocal
rendezvous rows, zone-only GNSS alerts, citation-label alignment, and per-lane counts.

The same audit removed another preview failure mode: hybrid retrieval always has a
least-irrelevant top-k result, so unrelated OSINT cards could appear beside a domain-level Ocean
query. The OSINT retrieval boundary now requires at least one real subject-token overlap (while
retaining the existing subject-less follow-up behavior), so top-k noise is not presented as
supporting evidence.

**Recorded limitation:** v2 routing is lexical by design—free, instant, and explainable, but it
can miss an indirect domain reference or over-route an ambiguous term. Subject-less queries
and explicit all-source requests intentionally broadcast to every lane, sacrificing precision to
avoid a false negative when conversation context is unavailable. The current 1.00 is therefore
reported only on the eleven labelled query shapes, not as a general semantic-routing claim.

### 6. Backend parity
Both available backends scored on the **same** gold set (10 queries), by the **cross-family**
NLI scorer rather than the self-judging LLM, so the cost of running key-free is explicit.

| Backend | Citation support | Faithfulness | Strict faithfulness | Trap breaches | Notes |
|---|---|---|---|---|---|
| deterministic (extractive) | **0.475** | **0.583** | 0.633 | 0/10 | always-on floor; no key |
| local Ollama (`qwen2.5:14b`) | 0.183 | 0.383 | 0.100 | 1/10 | self-judged as 0.65 / 0.90 |
| Claude (Anthropic API) | not run | not run | not run | — | needs a key; not measured |

**The free deterministic path is the more grounded one.** On cross-family scoring the
extractive fallback beats the 14B local model on faithfulness (0.583 vs 0.383) and citation
support (0.475 vs 0.183), and it never breached a calibration trap where the model breached
one. The LLM judge reported the opposite ranking for the model (0.90 faithfulness) — which is
precisely why the self-judged number is not the one published.

**Read the gap with two corrections, both of which cut against the headline.** First,
entailment metrics structurally favour extraction: the template restates source sentences, so
its claims are near-verbatim entailed, while a model that *synthesises* is penalised for
paraphrase — the strict variant (0.633 vs 0.100) is mostly measuring that, not reasoning
quality. The atomic/decomposed variant is the fairer comparison and still favours the
template. Second, n=10 queries with 1–3 judgments each is a small denominator; these separate
"clearly different" from "clearly the same", not 0.38 from 0.45.

What survives both corrections: **paying nothing costs nothing in groundedness here**, and a
local 14B model is not a free upgrade over deterministic extraction on this gold set.

Reproduce (locally, where the models are present — the run downloads the NLI cross-encoder):

```
ARGUS_NLI_ENABLED=true make eval                                   # deterministic backend
ARGUS_NLI_ENABLED=true ARGUS_LLM_BACKEND=ollama \
  ARGUS_OLLAMA_MODEL=qwen2.5:14b make eval                         # local model
```

## Gold set

A small, hand-curated set of analyst queries with: relevant-document labels, a set of claims a
correct brief should make, and known traps (topics with thin/low-reliability sourcing where the
*right* answer is low confidence + an explicit intelligence gap). Lives under
`src/argus/eval/`. Kept deliberately small and honest rather than large and noisy.

## Harness status

`make eval` (`argus.eval.run`) scores a fixture gold set (`src/argus/eval/goldset.py`).
Retrieval metrics are deterministic (LLM-free, CI-safe); brief metrics use whatever backend
is available (local Ollama, else the template digest).

**Deterministic baseline (template backend, fixture corpus)** — auto-recorded below by
`make eval` (never hand-edited). The fixture corpus is small and lexically clean, so
retrieval=1.00 mainly guards against regressions — the discriminating checks are citation
coverage, fabrication, and the trap.

<!-- AUTOGEN:eval-results (regenerated by `make eval`; do not edit by hand) -->
_Auto-recorded by `make eval` — backend `ollama:qwen2.5:14b`._

| Query | recall@k | MRR | confidence | cite-coverage | citations | fabricated |
|---|---|---|---|---|---|---|
| What is happening at the disputed reef? | 1.00 | 1.00 | moderate | 1.00 | 3 | 0 |
| What is known about the earthquake in the  | 1.00 | 1.00 | moderate | 1.00 | 3 | 0 |
| Who won the election? | 1.00 | 1.00 | moderate | 1.00 | 2 | 0 |
| What did the central bank decide on intere | 1.00 | 1.00 | moderate | 1.00 | 1 | 0 |
| Was the nationwide power outage caused by  | 1.00 | 1.00 | moderate ⚠️OVER | 1.00 | 2 | 0 |
| Has the president fled the capital? | 1.00 | 1.00 | high ⚠️OVER | 1.00 | 3 | 0 |
| Are armored columns massing at the border? | 1.00 | 1.00 | low | 1.00 | 1 | 0 |
| Who fired first in the border clash? | 1.00 | 1.00 | moderate | 1.00 | 1 | 0 |
| Was the grid disruption a cyberattack? | 1.00 | 1.00 | moderate | 1.00 | 1 | 1 |
| How many casualties were reported in the b | 1.00 | 1.00 | moderate ⚠️OVER | 1.00 | 2 | 0 |

- **mean recall@3**: 1.00
- **mean MRR**: 1.00
- **mean citation coverage**: 1.00
- **fabrication attempts caught (dropped)**: 1
- **calibration trap breaches**: 3 (brief exceeded the confidence a single low-reliability source warrants)
- **mean faithfulness (grounded claims, LLM-judge)**: 0.90
- **mean citation support (cited evidence backs the claim, LLM-judge)**: 0.50
- **mean NLI faithfulness (atomic claim decomposition, deterministic)**: 0.33
- **mean NLI citation support (atomic claim decomposition, deterministic)**: 0.28
- **mean NLI faithfulness (strict whole-judgment entailment, experimental)**: 0.10
- **mean NLI citation support (strict whole-judgment entailment, experimental)**: 0.10
<!-- /AUTOGEN:eval-results -->

**LLM-path (multi-agent deliberation, structured outputs, `ollama:qwen2.5:14b`, 10-query set).**
The **AUTOGEN block above is the authoritative record**; this is the honest reading of it. The
set was deliberately expanded from 3 to 10 queries (6 of them calibration/contested caps) so
the calibration and judge metrics are means over many cases rather than one lucky (or unlucky)
draw. What the larger set shows:

- **Calibration is the recurring weak spot, and it is variable run-to-run** (the ⚠️OVER flags
  and the "calibration trap breaches" count in the AUTOGEN block are the authoritative per-run
  record). The stable finding across every run: **single low-reliability, sensational claims —
  a foreign-sabotage blackout, a coup rumour — are where the model over-reaches.** The
  power-outage sabotage trap has breached its *low* cap in every run; other runs have also rated
  the president-fled coup rumour as high as *high* and the casualty-gap query *moderate*. The
  contested border clash and single-analyst grid claim, by contrast, stay within their *moderate*
  caps. The model does not adequately discount a lone D/F-rated source on a dramatic claim — the
  concrete fix is a **reliability-gated confidence cap** (hard-limit confidence when the only
  sourcing is low-reliability), not more prompt-nudging. This is the highest-value calibration
  fix outstanding.
- **Citation coverage 1.00, retrieval recall@3 1.00** over the 20-doc corpus (now a real filter
  with distractors, not a formality); the resolvability invariant drops every non-resolving
  citation label — the AUTOGEN "fabrication attempts caught" count audits it (fabrications caught,
  never shown).

**Recorded negatives (kept honestly):**

- **Citation precision remains unproven, and the LLM judge is the limiting instrument.** The
  adjudicator-prompt tightening aimed at the LLM-judge citation-support score; that score was
  **0.67 (3-query) then 0.60 (first 10-query run)** and has stayed ~0.5–0.6 since — no evidence of
  improvement, and the judge itself is mediocre and noisy run-to-run. Self-LLM-judging (the
  generator's family scoring its own briefs) is too *stochastic* and self-biased to certify the
  claim. Citation
  precision ships as sound tradecraft, not a demonstrated gain.
- **Judge–human agreement, now measured — and a partial negative on the NLI fix.** We built the
  proposed deterministic, cross-family **NLI entailment scorer** (`src/argus/eval/nli.py`;
  claim-level entailment via `cross-encoder/nli-deberta-v3-base`; opt-in `ARGUS_NLI_ENABLED`) to
  replace the biased self-judge, and measured both judges against a hand-labelled 10-pair
  entailment slice (`ENTAILMENT_GOLD`). Result, kept honestly:

  | Judge | Agreement with human labels |
  |---|---|
  | NLI entailment (deterministic, cross-family) | **9/10 = 0.90** — missed one paraphrase ("certified as credible" → "found credible") |
  | LLM judge (qwen2.5:14b, temp 0) | **10/10 = 1.00** — including every allegation-vs-fact trap |

  So the NLI scorer is **not** a per-item accuracy win over the LLM judge on clean, isolated
  cases — a base NLI model can whiff on paraphrase. The LLM judge's real weakness was never
  accuracy on clear cases; it is *stochasticity and self-bias on full briefs*. NLI's value is
  therefore orthogonal, not superior: it is **deterministic** (zero run-to-run variance) and
  **cross-family** (no self-bias), so it is shipped as a stability cross-check reported beside
  the LLM judge (`ARGUS_NLI_ENABLED=1 make eval`), not as a replacement. A larger labelled slice
  and a stronger NLI model (or a judge ensemble) would sharpen this; the 10-pair result is a
  one-item margin and is stated as such.
- **Bigger negative: strict entailment is the wrong bar for *analytic* judgments.** On full
  briefs the strict whole-judgment NLI scores collapse toward ~0.1 (AUTOGEN block, labelled
  *experimental*) — far below the LLM judge and below NLI's own 0.90 on the atomic slice. Not a
  bug (citations resolve as `E#`; verified) and not a sign the briefs are unfaithful: a real key
  judgment is an *assessment* that synthesizes, hedges and infers beyond any one evidence line,
  and strict entailment (the hypothesis must be *necessarily* true given the premise) marks those
  "neutral", not "entailed". Concretely, the reef judgment *"There is likely an ongoing maritime
  territorial dispute… a show of force rather than immediate intent for direct confrontation
  [E1][E2][E3]"* scores **0.00 entailment against all three** corroborating sources, though it is
  a sound synthesis. So whole-judgment NLI is **not a valid faithfulness metric for analytic
  writing** — the fix is **atomic claim decomposition**.
- **Atomic claim decomposition — the fix, built and validated.** `decompose()` (in `eval/nli.py`)
  splits a judgment into atomic factual sub-claims (deterministic clause split + estimative-hedge
  stripping — a free, bias-free approximation of RAGAS's LLM claim extraction);
  `score_brief_nli(decompose_claims=True)` scores each, so faithfulness is the *fraction of
  sub-claims entailed*, and `make eval` reports the atomic metric beside the strict one (the lift
  — roughly 3x this run — is on the record). On the reef judgment that scored 0.00 strict,
  decomposition separates the grounded fact *"an ongoing maritime territorial dispute near the
  disputed reef"* (entailment **0.98**) from the ungrounded inference *"a show of force rather
  than immediate intent for direct confrontation"* (**0.00**) for an honest atomic faithfulness
  of **0.50** — half grounded reporting, half analytic inference beyond the evidence. **Two honest
  limits remain:** (1) the atomic aggregate is still well below the LLM judge, because the two
  encode *different definitions of "faithful"* — strict entailment vs. the LLM's lenient (and
  self-optimistic) "reasonable grounding"; adjudicating which is right needs a human-labelled
  faithfulness set, the next eval step. (2) the deterministic clause-splitter is crude on some
  sentences; an LLM decomposer would be RAGAS-faithful but reintroduce a model dependency — the
  zero-cost splitter is the deliberate choice.
- **The multi-agent panel is fragile under local-model latency.** The red-team `Critiques`
  structured step **intermittently times out** (qwen too slow on that JSON schema within the 300s
  budget) — between 1 and 5 of the 10 queries across runs — so those briefs run on a degraded
  (unchallenged) panel and their per-query numbers reflect the digest fallback, not the full
  debate. The brief always returns (resilience working as designed) but a degraded panel is a
  weaker analyst. Worth fixing (smaller/faster Critiques output, a lighter judge model, or a
  longer budget), and stated plainly rather than reporting to the best run.

**Distilled student (one-shot, MLX LoRA `Qwen2.5-3B-Instruct-4bit` + adapter)** — measured
through the same harness in `student` mode, against the same base model with **no** adapter:

| Model | cite coverage | confidence (trap query) | trap breaches | fabrications caught |
|---|---|---|---|---|
| base 3B (no adapter) | 0.00 | — (no calibrated call) | 0 | 0 |
| **distilled student (LoRA)** | **1.00** | **low** (correct) | 0 | 2 |

- **Distillation taught the tradecraft.** The base 3B doesn't produce the ARGUS sectioned,
  cited brief at all (coverage 0.00, no confidence call). After LoRA self-distillation on the
  teacher's eval-passing briefs, the student writes calibrated, fully-cited judgments
  (coverage 1.00) and **held the calibration trap at `low`** — the format and the discipline
  transferred to a model ~5× smaller.
- **Faster but weaker, honestly.** A 3B one-shot vs the 14B panel: the student made **2
  fabrication attempts** (cited labels that didn't resolve — dropped by the resolvability
  invariant, never shown) where the teacher made 0. It also overfit the **4-example
  smoke-test set** (train loss → 0.003, val loss rising), so this validates the *pipeline*,
  not a production model. Scale the distillation set (`make ingest` across more topics +
  `DISTILL_QUERIES`) for a stronger student.

## Recorded negatives (where it fails)

The honest half. To be filled as found — e.g. thin-source topics where the agent overstates
confidence, non-English reporting it under-retrieves, coordination false positives on organic
viral events. Each negative gets characterized (why it fails, when), not hidden.

- **Template digest is not calibration-aware** — it is a relevance-ranked evidence digest, so
  it always reports *low* confidence and makes no analytic judgment. Honest by construction
  (it never overstates), but it is not a substitute for the deliberated brief.
- **Models cite labels inconsistently** — qwen2.5:14b sometimes wrote `[1]` instead of `[E1]`,
  which originally resolved to *zero* citations on the reef query. The eval caught it (3
  fabrications, 0 citations); citation resolution was then made tolerant of label variants
  (`1` / `E1` / `[E1]` / raw doc id all resolve). A concrete case of the eval driving a fix.
- **Confidence is mildly stochastic** — the same single-source query drifted low↔moderate
  across runs. Acceptable here (never breaching the trap), but a reason to keep `temperature`
  low and, later, to report confidence over multiple samples.
