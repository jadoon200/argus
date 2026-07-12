# Hugging Face Spaces (Docker SDK) image for the public ARGUS demo.
#
# A Space repo is built from its OWN root `Dockerfile`, and HF gives no way to point at a
# different file — so rather than the repo's `Dockerfile.web`, this self-contained image
# CLONES ARGUS from GitHub and builds it. That keeps the Space a tiny two-file repo and
# leaves the main repo's Dockerfiles untouched. It mirrors `Dockerfile.web` (kept in sync
# by hand); see this folder's README for the push steps.
#
# Override the ref to pin a tag/commit:  Space Settings → Variables → ARGUS_REF=v1.0.0
ARG ARGUS_REF=main
ARG ARGUS_REPO=https://github.com/jadoon200/argus

# --- stage 1: build the dashboard -----------------------------------------------------
FROM node:20-slim AS web
ARG ARGUS_REF
ARG ARGUS_REPO
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${ARGUS_REF} ${ARGUS_REPO} /src
WORKDIR /src/frontend
# A production build => import.meta.env.PROD, so the client calls the API same-origin.
RUN npm ci && npm run build

# --- stage 2: API + built dashboard ---------------------------------------------------
FROM python:3.12-slim AS app
ARG ARGUS_REF
ARG ARGUS_REPO
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${ARGUS_REF} ${ARGUS_REPO} /app
WORKDIR /app
# Slim runtime (no ML stack); the demo pins ARGUS_LLM_BACKEND=template.
RUN pip install --no-cache-dir -r requirements-api.txt \
    && pip install --no-cache-dir --no-deps .
COPY --from=web /src/frontend/dist ./frontend/dist

# Bake a small demo corpus so the Space isn't empty on first load.
ENV ARGUS_DATABASE_URL=sqlite:////app/data/argus.db
RUN mkdir -p /app/data && python scripts/seed_demo.py

# Free-demo posture: template engine (no key, no cost), answer from the baked corpus (the
# slim image has no embedding model), and trust HF's reverse-proxy X-Forwarded-For header.
ENV ARGUS_LLM_BACKEND=template \
    ARGUS_AUTO_COLLECT=false \
    ARGUS_API_TRUST_FORWARDED_HEADER=true

# HF Spaces routes external traffic to `app_port` (declared in README.md); 7860 is its default.
EXPOSE 7860
CMD ["uvicorn", "argus.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
