.PHONY: env install lock lint typecheck test check up down migrate ingest enrich narratives brief eval api ui

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

# Generate a cited intelligence brief for a question.
#   make brief Q="What happened in the South China Sea this week?"
brief:
	python -m argus.agent.analyst "$(Q)"

# Score the analyst agent/RAG on the gold query set (results -> docs/EVAL.md).
eval:
	python -m argus.eval.run

# Serve the read-only API + the agent /brief route on :8000
api:
	uvicorn argus.api.app:app --reload

# React dashboard dev server on :5173 (needs make api in another shell)
ui:
	npm --prefix frontend install && npm --prefix frontend run dev
