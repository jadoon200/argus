"""Export persisted briefs to ``scripts/seed_briefs.json`` for the demo seed.

Workflow (run locally, where a real model is available):

    ARGUS_DATABASE_URL=sqlite:////tmp/seed.db python scripts/seed_demo.py
    ARGUS_DATABASE_URL=sqlite:////tmp/seed.db ARGUS_AUTO_COLLECT=false \
        python -m argus.agent.analyst "<each dashboard example question>"
    ARGUS_DATABASE_URL=sqlite:////tmp/seed.db python scripts/export_seed_briefs.py

``seed_demo.py`` then bakes these snapshot briefs into every fresh demo image, so the
model-less cloud deploy can serve the example questions as complete deliberated products
(the dashboard's snapshot path). Generate AGAINST THE SEED CORPUS with auto-collect off —
citations must resolve to seed doc ids, or the dashboard can't hydrate evidence cards.
Model-produced (non-template) briefs only: a template digest is what the deploy already
produces live, so snapshotting one would be dishonest labelling.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from argus.db.base import get_session_factory
from argus.db.models import Brief

OUT = Path(__file__).with_name("seed_briefs.json")

FIELDS = (
    "query",
    "body",
    "key_judgments",
    "citations",
    "confidence",
    "key_assumptions",
    "indicators",
    "hypotheses",
    "ach_ranking",
    "alternatives",
    "gaps",
    "critique_response",
    "backend",
)


def main() -> None:
    with get_session_factory()() as session:
        rows = session.scalars(select(Brief).order_by(Brief.brief_id)).all()
        exported = [
            {f: getattr(b, f) for f in FIELDS}
            for b in rows
            if b.backend and b.backend != "template"
        ]
    OUT.write_text(json.dumps(exported, indent=2) + "\n")
    print(f"exported {len(exported)} snapshot brief(s) -> {OUT}")


if __name__ == "__main__":
    main()
