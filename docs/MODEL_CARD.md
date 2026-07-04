# Model card — ARGUS analyst agent

> Seed card. Sections marked `TBD` fill in as the system reaches MVP. The point of writing it
> now is that the *intended* use, limits, and failure modes are committed before the results
> are, so the evaluation can't quietly move the goalposts.

## Overview

ARGUS is an **all-source open-source-intelligence (OSINT) analysis aid**. Its central artifact
is a **cited intelligence brief**: given an analyst query, a **multi-agent deliberation panel**
(LangGraph) retrieves over a corpus of open-source reporting (GDELT global news + curated RSS)
and argues the judgment out using real intelligence tradecraft — competing hypotheses,
analyst ↔ red-team debate, ACH adjudication (favour the least-disconfirmed hypothesis), and
IC estimative language (ICD 203 / Sherman Kent) — to produce a structured assessment: key
judgments, a confidence call, the most credible alternative, intelligence gaps, and inline
citations that **all resolve to real ingested documents** (fabricated citations are dropped,
never shown).

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

Pluggable, free by default (`ARGUS_LLM_BACKEND`). `auto` mode selects local Ollama if
reachable (recommended: `qwen2.5:14b` on an M3 Pro; `llama2` is too weak) and otherwise
falls back to the deterministic extractive briefer — which always runs with no key and
honestly reports only `low` confidence. Other options: `mlx` (Apple-Silicon-native local
inference via mlx-lm, and the way the fine-tuned student is served), `openai` (any
OpenAI-compatible server — vLLM/llama.cpp/LM Studio/groq — free when local), and
`anthropic` (Claude, **opt-in only**, never auto-selected). All backends are scored on the
same gold set so the key-free floor is explicit.

### Confidence calibration

By default, a single brief's confidence is a point estimate. **High-assurance mode**
(`ARGUS_ASSURANCE_SAMPLES` > 1) samples the adjudicator K times and derives the *reported*
confidence from agreement: if the panel converges on the same call (unanimous or strong
majority), confidence is reported as-is; if the samples wobble (< 2/3 agreement), it is
downgraded one level — an honest recalibration against stochastic drift, not optimistic
cherry-picking of a lucky draw.

## Brief-generation modes & the distilled student

Three ways to produce a brief, each measured on the same harness:

- **Multi-agent panel** (`ARGUS_BRIEF_MODE=panel`, default) — the full ACH deliberation;
  highest quality, several LLM calls.
- **Optimized single-shot** (`ARGUS_BRIEF_MODE=dspy`) — a DSPy-compiled prompt
  (`make optimize`) that one-shots the brief; faster, no debate.
- **Distilled student** (`ARGUS_LLM_BACKEND=mlx` + a LoRA adapter) — a small local model
  (e.g. Qwen2.5-3B) **self-distilled** from the teacher's eval-passing briefs (only briefs
  that are cited, non-empty, and calibrated become training targets). It one-shots a brief
  and is **faster but weaker** than the 14B teacher — a real, measured trade-off (see
  `docs/EVAL.md` / `docs/FINETUNE.md`), not free quality. The full panel stays the path for
  the highest-stakes assessments.

## Evaluation

Full methodology and results in [`docs/EVAL.md`](EVAL.md): retrieval recall, **citation
accuracy** (resolvable + supporting via LLM-as-judge), **faithfulness/groundedness** (now
measured), source-reliability calibration, and cross-backend parity — with recorded negatives.
**Citation precision** is now tightened via adjudicator prompt instruction: cite an item ONLY
if it *directly* supports the specific judgment, not tangential or topic-adjacent citations
(targets the LLM-as-judge "citation support" metric). **Measured effect: none yet** — citation
support is 0.67 both before and after the change on the 3-query set, a recorded negative; the
set is too small/stochastic to detect a real effect, so it ships as sound tradecraft, not a
demonstrated gain (see the recorded negatives in [`docs/EVAL.md`](EVAL.md)). Across runs the
LLM-path numbers swing (mean faithfulness 0.67-1.00, citation support ~0.67), and a timed-out
deliberation step can degrade calibration on a given query — reported honestly rather than to
the best run.

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

Defensive/analytical, public data only. See README → *Responsible use*.
