# Deployment notes — taking ARGUS public

> **Status: deploy-ready.** The whole app ships as one free container — FastAPI serves the built
> React dashboard from the same origin as the API, on a SQLite file, with the deterministic
> template engine (no API key, no cost). The Render blueprint also wires the three read-only
> sibling intelligence APIs for Sky/Ocean/Cyber fusion. The hardening notes further down apply
> to any larger deployment.

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

### Render free tier + keep-alive (recommended free host)

Render still hosts a Docker web service for **$0**, and its one downside — sleeping after ~15 min
idle, then a ~30-60s cold start — is neutralised for free by a scheduled keep-alive ping.

1. Push to GitHub, then **New → Blueprint** on [render.com](https://render.com) pointing at
   [`render.yaml`](../render.yaml). Render builds `Dockerfile.web`, injects `$PORT`, terminates TLS,
   and gives you a `https://argus-XXXX.onrender.com` URL. No card, no key, no database server.
2. Keep it warm: set the repo **variable** `RENDER_URL` to that URL
   (*Settings → Secrets and variables → Actions → Variables*). The bundled
   [`keep-alive` workflow](../.github/workflows/keepalive.yml) then pings `/health` every ~10 min on
   GitHub's free Actions minutes, so the service never sleeps. (A free uptime monitor such as
   UptimeRobot or cron-job.org does the same job if you'd rather not run a workflow.)

### Multi-agent fusion wiring

`render.yaml` enables the deterministic supervisor and points each worker at the portfolio's
live, read-only sibling API:

```bash
ARGUS_FUSION_SUPERVISOR=true
ARGUS_HORUS_API_URL=https://horus-kc7w.onrender.com
ARGUS_PHAROS_API_URL=https://pharos-0y6q.onrender.com
ARGUS_SENTINEL_API_URL=https://sentinel-92pf.onrender.com
```

The same non-secret defaults are baked into `Dockerfile.web`. This keeps direct container
deploys and existing Render services functional even when a service auto-deploys the image
without first re-synchronising changed Blueprint environment variables; explicit environment
values still override the image defaults.

No credentials or writes cross these links. A failed or sleeping sibling contributes no
evidence and never fails the brief; `/overview` reports it unreachable. The overview fan-out is
cached for 60 seconds (`ARGUS_FUSION_OVERVIEW_CACHE_SECONDS`) so tab opens do not hammer the
free services. A first request can still miss a cold sibling—the next request sees it after the
instance wakes. `ARGUS_FUSION_SUPERVISOR=false` restores the previous flat all-lanes gather.

For local development, copy [`.env.example`](../.env.example) to `.env`, or run a one-off live
source smoke through `make fusion-demo Q="..."`.

### Hugging Face Spaces (needs PRO as of 2026)

> **Heads-up:** HF now requires a **PRO subscription ($9/mo)** to host Docker (or Gradio) Spaces —
> only *static* Spaces are free, which can't run this FastAPI app. The config in
> [`deploy/huggingface/`](../deploy/huggingface/) still works **if you have PRO**: create a Docker
> Space, copy in its two files (`Dockerfile` + `README.md`), and push — it clones this repo, builds
> the dashboard, and serves it on port 7860 at `https://<you>-argus.hf.space`. Refresh after new
> commits with **Settings → Factory rebuild**.

**Fly.io** is another warm-and-free-within-allowance option from `Dockerfile.web`, but it wants a
card on file and its free VMs are RAM-constrained. All hosts build the same single-origin image.

Because the dashboard is served same-origin, its API calls are relative and need **no** CORS config
or baked-in hostname. To host the static site and the API on *different* origins instead, build the
frontend with `VITE_API_URL=https://api.example.com` and set `ARGUS_API_ALLOWED_ORIGINS` on the API
(see the table below).

To answer with a real deliberated panel instead of the template digest, point the deployment at a
local Ollama (`ARGUS_LLM_BACKEND=ollama`, `ARGUS_OLLAMA_URL=...`) or any OpenAI-compatible server —
still key-free — and drop `ARGUS_AUTO_COLLECT=false` to re-enable collect-on-demand (needs the full
image with the embedding model, not the slim API stack).

### Live model on the free cloud deploy (Groq free tier, optional)

The demo deploy can't run a local model (free-tier RAM), but Groq's developer tier is genuinely
free (no card; verified 2026-07: `llama-3.3-70b-versatile` at 30 req/min, 1K req/day, 12K
tokens/min, 100K tokens/day — enough for quick-mode briefs on a portfolio demo) and speaks the
OpenAI API, so ARGUS's `openai` backend works as-is. On Render, set:

```bash
ARGUS_LLM_BACKEND=openai
ARGUS_OPENAI_BASE_URL=https://api.groq.com/openai/v1
ARGUS_OPENAI_MODEL=llama-3.3-70b-versatile
ARGUS_OPENAI_API_KEY=<your free key from console.groq.com>
ARGUS_BRIEF_MODE=quick   # panel mode burns ~30-40K tokens/brief; quick fits the TPM budget
```

Notes: the free tier is per-organization and can throttle mid-deliberation (12K TPM), which is
why `quick` is the sensible deployed default — the router's panel escalation is a local-model
luxury. If the key is absent or Groq errors, deliberation resilience degrades the brief to the
deterministic digest rather than failing; the dashboard's snapshot path (precomputed full-panel
briefs for the example questions) keeps working either way. Re-verify the tier before relying on
it — free tiers change (see the snapshot path for the zero-dependency fallback).

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
| `ARGUS_FUSION_SUPERVISOR` | `true` | Route to OSINT plus only relevant Sky/Ocean/Cyber workers. `false` broadcasts to all configured lanes for rollback/A-B comparison. |
| `ARGUS_HORUS_API_URL` | `""` | Read-only Sky worker base URL; empty disables the lane. |
| `ARGUS_PHAROS_API_URL` | `""` | Read-only Ocean worker base URL; empty disables the lane. |
| `ARGUS_SENTINEL_API_URL` | `""` | Read-only Cyber worker base URL; empty disables the lane. |
| `ARGUS_FUSION_OVERVIEW_CACHE_SECONDS` | `60` | TTL for server-side sibling status/count/last-item fan-out. |

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
- **Sibling bridges** — prefer private-network URLs in a hardened deployment. The public demo
  uses the siblings' public read-only APIs; ARGUS never writes to HORUS, PHAROS, or SENTINEL.

## Minimal prod env example

```bash
ARGUS_API_ALLOWED_ORIGINS=https://argus.example.com
ARGUS_API_TRUST_FORWARDED_HEADER=true   # behind a trusted proxy that sets X-Forwarded-For
ARGUS_LLM_BACKEND=template              # key-free + cost-free for the public demo
# tighten if the host is small:
# ARGUS_API_RATE_LIMIT_REQUESTS=10
# ARGUS_API_INFERENCE_CONCURRENCY=1
```
