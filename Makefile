.PHONY: env install lock lint typecheck test check up down migrate ingest enrich narratives hydrate brief eval api ui

# One-time: create the conda env, then `conda activate argus`
env:
	conda create -y -n argus python=3.12

# Run inside the activated argus env
install:
	pip install -r requirements-dev.txt && pip install -e .

# Refreeze the pinned lock (CI and Docker install from it)
lock:
	printf -- '--extra-index-url https://download.pytorch.org/whl/cpu\n\n' > requirements.lock
	pip freeze --exclude-editable >> requirements.lock

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy

test:
	pytest

check: lint typecheck test

up:
	docker compose up -d db && docker compose run --rm migrate

down:
	docker compose down

migrate:
	alembic upgrade head

# Collect open-source reporting on a topic (GDELT DOC 2.0 + curated RSS).
#   make ingest Q="South China Sea"
ingest:
	python -m argus.ingest.flows "$(Q)"

# Entity/event extraction + dedup + Admiralty credibility scoring over the corpus.
enrich:
	python -m argus.nlp.enrich

# Narrative clustering + coordination detection (Layer 2b).
narratives:
	python -m argus.narrative.run

# Backfill article text for headline-only documents (ingested before hydration existed),
# then re-enrich and refresh narratives over the real text.
hydrate:
	python -m argus.nlp.fulltext

# Generate a cited intelligence brief for a question.
#   make brief Q="What happened in the South China Sea this week?"
brief:
	python -m argus.agent.analyst "$(Q)"

# Closing-the-loop collection: brief -> gaps -> targeted queries -> ingest -> re-brief.
#   make collect-loop Q="What is driving tensions in the South China Sea?"
collect-loop:
	python -m argus.collection.loop "$(Q)"

# The optimized single-shot brief via the DSPy-compiled program (run `make optimize`
# first; needs the `optimize` extra). Same as `ARGUS_BRIEF_MODE=dspy make brief`.
brief-dspy:
	python -m argus.optimize.serve "$(Q)"

# Score the analyst agent/RAG on the gold query set (results -> docs/EVAL.md).
eval:
	python -m argus.eval.run

# Compile (optimize) the brief prompt against the eval metric on the local model.
# Needs the optimize extra: pip install -e .[optimize]
optimize:
	python -m argus.optimize.compile

# Self-distillation fine-tune (Apple Silicon). 1) build a dataset from the teacher's
# eval-passing briefs, 2) LoRA fine-tune a small student, 3) serve it via the mlx backend.
# Needs the mlx extra on a Mac: pip install -e .[mlx]. See docs/FINETUNE.md.
FT_MODEL ?= mlx-community/Qwen2.5-3B-Instruct-4bit
FT_ITERS ?= 300
finetune-data:
	python -m argus.finetune.dataset

finetune:
	python -m mlx_lm.lora --model $(FT_MODEL) --train --data data/finetune \
		--adapter-path data/finetune/adapter --iters $(FT_ITERS) --batch-size 1

# Serve the read-only API + the agent /brief route on :8000
api:
	uvicorn argus.api.app:app --reload

# React dashboard dev server on :5173 (needs make api in another shell)
ui:
	npm --prefix frontend install && npm --prefix frontend run dev
