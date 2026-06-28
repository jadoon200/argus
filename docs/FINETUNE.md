# Fine-tuning ARGUS to the analyst purpose (MLX LoRA, free)

The third "tune to our purpose" lever (after domain-specialized prompts and DSPy): **distil
the multi-agent panel's tradecraft into a small, fast, local model**. Free and Apple-Silicon
native — no API, no cloud, runs on the M3.

## Why self-distillation

We don't have a labelled corpus of intelligence briefs, and we don't need one. The strong
**teacher** (qwen2.5:14b, run through the full multi-agent deliberation) already produces
ARGUS-style cited briefs. We keep only the teacher outputs that **pass the eval bar** (cited +
non-empty + calibrated) and train a small **student** to one-shot them. The student learns to
produce what the panel deliberates — much faster, and entirely offline.

The honesty bar is built into the data: a brief that fabricates citations or fails coverage is
never used as a training target.

## Workflow

```bash
pip install -e .[mlx]        # on a Mac (mlx is darwin-only)
ollama pull qwen2.5:14b      # the teacher

# 1) Build the dataset — teacher generates eval-passing briefs as chat examples.
make finetune-data           # -> data/finetune/{train,valid}.jsonl

# 2) LoRA fine-tune a small student on Apple Silicon.
make finetune                # -> data/finetune/adapter/   (override FT_MODEL / FT_ITERS)

# 3) Serve the fine-tuned student as an ARGUS backend.
ARGUS_LLM_BACKEND=mlx \
ARGUS_MLX_MODEL=mlx-community/Qwen2.5-3B-Instruct-4bit \
ARGUS_MLX_ADAPTER_PATH=data/finetune/adapter \
make brief Q="What is driving tensions in the South China Sea?"
```

## Scaling up

`dataset.py:build_items()` already scales automatically: it always includes the gold seed
(`gold_items()`, each query paired with its **retrieved** evidence so training matches
inference) **plus** corpus-harvested items (`corpus_items()`) — it runs the curated
`DISTILL_QUERIES` against whatever you've ingested and pairs each with real retrieved
evidence. So the recipe for a stronger student is simply: ingest more (`make ingest` across
many topics) and enrich (`make enrich`), then `make finetune-data` — the teacher turns each
harvested (query, evidence) into an eval-passing brief. Widen `DISTILL_QUERIES` for more
topical coverage. More diverse, eval-passing examples → a better student.

## Honest expectations

- A 3B student distilled from a 14B teacher will be **faster but weaker**; measure it on the
  same `make eval` harness and record the gap (it is a real trade-off, not free quality).
- The student one-shots a brief; it does **not** reproduce the full analyst↔red-team debate.
  Keep the multi-agent path for the highest-stakes assessments.
- Training time and quality depend on dataset size and iters; treat the seed run as a smoke
  test of the pipeline, not a finished model.
