---
title: ARGUS
emoji: 👁️
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: All-source intelligence workbench — cited briefs from open sources
---

# ARGUS — all-source intelligence workbench

Open-source reporting → **cited intelligence briefs**. ARGUS collects global news (GDELT +
curated wire/agency RSS), rates every source on the **NATO Admiralty** reliability scale,
watches for **coordinated narratives** (DISARM influence-ops tagging), and fuses it into cited
briefs via a multi-agent **Analysis of Competing Hypotheses** panel.

This Space is a **free public demo**: it runs the deterministic *template* engine (no API key,
no cost) over a small baked-in corpus, so every judgment cites real, source-rated evidence —
just not the full deliberated panel (that runs locally against a free local model). Source:
**https://github.com/jadoon200/argus**

> These files are the deploy config, not the app. The Space's `Dockerfile` clones ARGUS from
> GitHub and builds the full-stack image (React dashboard served same-origin by FastAPI, on a
> SQLite file). To refresh after a new commit, use **Settings → Factory rebuild**.
