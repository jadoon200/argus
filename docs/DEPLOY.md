# Deployment notes — taking ARGUS public

> **Status: deploy-ready.** The whole app ships as one free container — FastAPI serves the built
> React dashboard from the same origin as the API, on a SQLite file, with the deterministic
> template engine (no API key, no cost). The hardening notes further down apply to any larger
> deployment.

## Free one-service deploy (recommended)

The public demo is a **single container**: the dashboard and the API share one origin (no CORS,
no separate database server, no LLM key).

- **Image:** [`Dockerfile.web`](../Dockerfile.web) — a multi-stage build that compiles the React
  app (`frontend/`) and serves it from FastAPI (`app.mount("/", StaticFiles(...))`). It bakes a
  small demo corpus ([`scripts/seed_demo.py`](../scripts/seed_demo.py)) so the site isn't empty
  on first load, and pins `ARGUS_LLM_BACKEND=template` + `ARGUS_AUTO_COLLECT=false` so it runs
  with no model and no outbound calls.
- **Storage:** a SQLite file (`ARGUS_DATABASE_URL=sqlite:////app/data/argus.db`). The API creates
  the schema on startup for SQLite (`init_sqlite_schema`), so there is **no migration step** — a
  fresh boot just works. (Postgres deployments still use Alembic; the startup hook is a no-op
  there.)

```bash
# Build + run locally (visit http://localhost:8000):
docker build -f Dockerfile.web -t argus .
docker run --rm -p 8000:8000 argus
```

**Render (free tier), one click:** push to GitHub, then *New → Blueprint* on render.com pointing at
[`render.yaml`](../render.yaml). Render injects `$PORT`, terminates TLS, and gives you the URL. The
free plan idles out after ~15 min and cold-starts (~30-60s) — fine for a demo. **Hugging Face
Spaces** (Docker SDK) and **Fly.io** work the same way from `Dockerfile.web`.

Because the dashboard is served same-origin, its API calls are relative and need **no** CORS config
or baked-in hostname. To host the static site and the API on *different* origins instead, build the
frontend with `VITE_API_URL=https://api.example.com` and set `ARGUS_API_ALLOWED_ORIGINS` on the API
(see the table below).

To answer with a real deliberated panel instead of the template digest, point the deployment at a
local Ollama (`ARGUS_LLM_BACKEND=ollama`, `ARGUS_OLLAMA_URL=...`) or any OpenAI-compatible server —
still key-free — and drop `ARGUS_AUTO_COLLECT=false` to re-enable collect-on-demand (needs the full
image with the embedding model, not the slim API stack).

## Larger / hardened deployments

The dashboard API (`src/argus/api/app.py`) is read-only over the knowledge graph apart from one
expensive route: `POST /brief`, which runs retrieval + the analyst agent (and, if configured, a
remote LLM call). That route is the only meaningful resource-exhaustion and cost vector.
Everything below exists so a public deployment **degrades gracefully (429/503) rather than
running the box out of memory or your API budget**.

Two layers do the work: app-level guards (already in code, tunable by env) and infra-level
controls (your job at deploy time). The app guards are belt-and-suspenders — the reverse proxy
is the primary defence.

## App-level (in code, configure via `ARGUS_*` env vars)

| Env var | Default | Purpose |
| --- | --- | --- |
| `ARGUS_API_ALLOWED_ORIGINS` | `""` | **Must set in prod.** Comma-separated exact origins for the deployed dashboard, e.g. `https://argus.example.com`. Empty keeps the localhost-only CORS regex used in dev. |
| `ARGUS_API_MAX_REQUEST_CHARS` | `4000` | Max characters of a query; longer → `422`. Also drives an early `413` body-size cut-off before the body is buffered. |
| `ARGUS_API_RATE_LIMIT_REQUESTS` | `20` | Per-client requests allowed per window on `/brief`; over → `429`. |
| `ARGUS_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | The rate-limit window. |
| `ARGUS_API_TRUST_FORWARDED_HEADER` | `false` | Derive the per-client rate-limit key from the first `X-Forwarded-For` hop. Leave **off** unless behind a trusted proxy that sets it — on a directly-exposed server the header is client-controlled and spoofable. Set `true` only behind the reverse proxy below. |
| `ARGUS_API_INFERENCE_CONCURRENCY` | `2` | Hard cap on simultaneous brief generations; bounds peak RAM/CPU and concurrent LLM calls. Excess requests wait, then `503`. |
| `ARGUS_API_INFERENCE_ACQUIRE_TIMEOUT_SECONDS` | `15` | How long a request waits for a free slot before `503`. |
| `ARGUS_LLM_BACKEND` | `auto` | `auto` (local Ollama if reachable, else deterministic template — **never** auto-selects the paid Claude), `ollama`, `mlx` (Apple-Silicon local), `openai` (any OpenAI-compatible server; free when local), `anthropic` (opt-in, needs `ANTHROPIC_API_KEY`), or `template`. In a public deploy, pin `template` or a local backend so a traffic spike can't run up an API bill. |

The rate limiter and concurrency cap are **single-process, in-memory**. With multiple workers
each gets its own counters — fine for a small deployment; for real limits put them at the proxy.

## Infra-level (your job at deploy)

- **Reverse proxy (nginx / Caddy)** — the primary defence: `client_max_body_size`, `limit_req`
  for cross-worker rate limiting, TLS termination. Set `ARGUS_API_ALLOWED_ORIGINS` to the
  `https://` origin; forward the real client IP and set `ARGUS_API_TRUST_FORWARDED_HEADER=true`.
- **Cap the LLM cost.** If the deployed agent uses the Anthropic backend (`ARGUS_LLM_BACKEND=anthropic`), the concurrency cap + rate limit bound spend, but the real safety valve is pinning `ARGUS_LLM_BACKEND=template` or `ollama` for the public demo. Never expose an un-throttled remote-LLM route. Note: `auto` mode never touches the paid backend on its own.
- **Don't expose the dev server.** Run uvicorn behind the proxy with a sane worker count
  (`uvicorn ... --workers N`), not bound to a public interface.
- **Database** — Postgres stays on a private network; never expose it. Secrets via env only.
- **Sentinel bridge** — `ARGUS_SENTINEL_API_URL` should point at Sentinel's read-only API on a
  private network. ARGUS only ever reads from it.

## Minimal prod env example

```bash
ARGUS_API_ALLOWED_ORIGINS=https://argus.example.com
ARGUS_API_TRUST_FORWARDED_HEADER=true   # behind a trusted proxy that sets X-Forwarded-For
ARGUS_LLM_BACKEND=template              # key-free + cost-free for the public demo
# tighten if the host is small:
# ARGUS_API_RATE_LIMIT_REQUESTS=10
# ARGUS_API_INFERENCE_CONCURRENCY=1
```
