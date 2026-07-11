"""Seed a demo corpus for a public deployment — deterministic, no ML stack, no network.

The free single-container demo pins ``ARGUS_LLM_BACKEND=template`` and runs on a SQLite file,
so a fresh deploy would otherwise start empty. This bakes a small, realistic corpus (rated
sources, documents, an event, two narratives, one full brief) so the live site has something
to show on first load — every source carries its real NATO-Admiralty grade from
``argus.sources``, so the ratings on screen are the genuine ones.

    ARGUS_DATABASE_URL=sqlite:////app/data/argus.db python scripts/seed_demo.py

Idempotent by construction: it drops and recreates the demo tables each run. Safe to run at
image-build time (baked into the container) or against a mounted volume.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus.db.base import Base, get_session_factory, make_engine
from argus.db.models import (
    Brief,
    Document,
    Event,
    EventDocument,
    Narrative,
    NarrativeDocument,
    Source,
)
from argus.sources import grade_for, info_for

# (label, published-days-ago, credibility, title, summary)
_ARTICLES: list[tuple[str, int, int, str, str]] = [
    (
        "reuters.com",
        1,
        3,
        "Chinese coast guard shadows Philippine resupply run near Second Thomas Shoal",
        "China Coast Guard vessels tracked a resupply mission to the grounded BRP Sierra Madre; "
        "a water cannon was deployed against a supply boat, Manila said.",
    ),
    (
        "apnews.com",
        1,
        3,
        "Manila protests 'aggressive' Chinese maneuvers in South China Sea standoff",
        "The Philippines lodged a diplomatic protest over what it called dangerous blocking "
        "maneuvers by Chinese vessels during a routine resupply.",
    ),
    (
        "bbc.com",
        2,
        2,
        "South China Sea: what is behind the Philippines-China flare-up?",
        "Analysis of why the Second Thomas Shoal has become a flashpoint in the wider maritime "
        "dispute over competing sovereignty claims.",
    ),
    (
        "channelnewsasia.com",
        2,
        2,
        "ASEAN urges restraint as maritime tensions rise",
        "The regional bloc called for de-escalation and progress on a binding code of conduct "
        "after the latest coast-guard confrontation.",
    ),
    (
        "scmp.com",
        1,
        2,
        "Beijing says Philippine vessels 'intruded' into Chinese waters",
        "China's foreign ministry defended the coast-guard action as lawful enforcement within "
        "its claimed nine-dash-line jurisdiction.",
    ),
    (
        "cnn.com",
        3,
        3,
        "US reaffirms defense-treaty commitment to the Philippines",
        "Washington restated that the mutual defense treaty covers armed attacks on Philippine "
        "vessels in the South China Sea.",
    ),
    (
        "rt.com",
        1,
        1,
        "West stoking tensions in South China Sea, Beijing says",
        "State outlet frames the standoff as a US-orchestrated provocation aimed at containing "
        "China's rise in the region.",
    ),
    (
        "globaltimes.cn",
        1,
        1,
        "Philippine 'provocations' backed by external forces, analysts say",
        "State-affiliated commentary attributes the confrontation to Washington's encouragement "
        "of Manila.",
    ),
]

_SHOAL_SOURCES = {"reuters.com", "apnews.com", "scmp.com", "rt.com", "globaltimes.cn", "cnn.com"}
_EXTERNAL_NARRATIVE_SOURCES = {"rt.com", "globaltimes.cn", "scmp.com"}


def _sources() -> list[Source]:
    rows = []
    for label in sorted({a[0] for a in _ARTICLES}):
        info = info_for(label)
        rows.append(
            Source(
                label=label,
                name=info.name if info else label,
                kind=info.kind if info else None,
                reliability=grade_for(label),  # the real Admiralty grade from the registry
            )
        )
    return rows


def _brief(now: datetime) -> Brief:
    body = (
        "KEY JUDGMENTS:\n"
        "- Escalation at Second Thomas Shoal is driven by competing sovereignty claims and "
        "China's coast-guard enforcement of its nine-dash-line [E1] [E2].\n"
        "- The US-Philippines mutual defense treaty raises the stakes of any armed "
        "incident [E6].\n\n"
        "CONFIDENCE: moderate - corroborated by reliable wires, but intentions remain opaque."
    )
    return Brief(
        query="What is driving tensions in the South China Sea?",
        body=body,
        key_judgments=[
            "Escalation at Second Thomas Shoal is driven by competing sovereignty claims and "
            "China's coast-guard enforcement of its nine-dash-line [E1] [E2]",
            "The US-Philippines mutual defense treaty raises the stakes of any armed incident, "
            "constraining both sides [E6]",
            "State-affiliated outlets are amplifying an 'external forces' framing not "
            "corroborated by independent reporting [E7]",
        ],
        citations=["reuters.com:demo00", "apnews.com:demo01", "cnn.com:demo05", "rt.com:demo06"],
        confidence="moderate",
        key_assumptions=[
            "China's coast guard continues gray-zone enforcement short of armed conflict",
            "Resupply missions to BRP Sierra Madre continue",
        ],
        indicators=[
            "Naval (not coast-guard) deployment or live-fire exercises near the shoal",
            "Formal invocation of the US-Philippines mutual defense treaty",
        ],
        hypotheses=[
            "Deliberate Chinese pressure campaign to force abandonment of the shoal",
            "Tit-for-tat escalation without central direction",
            "Domestic-audience posturing on both sides",
        ],
        ach_ranking=[
            {
                "hypothesis": "Deliberate Chinese pressure campaign to force abandonment of the "
                "shoal",
                "inconsistency": 0.3,
                "consistent": 4,
                "inconsistent": 1,
            },
            {
                "hypothesis": "Tit-for-tat escalation without central direction",
                "inconsistency": 0.9,
                "consistent": 2,
                "inconsistent": 2,
            },
            {
                "hypothesis": "Domestic-audience posturing on both sides",
                "inconsistency": 1.4,
                "consistent": 1,
                "inconsistent": 3,
            },
        ],
        alternatives=(
            "Tit-for-tat escalation without central direction remains credible; the incidents "
            "could reflect local commanders rather than a directed campaign."
        ),
        gaps=(
            "Intentions of Chinese leadership are opaque; no reporting on internal "
            "decision-making. Collection requirement: PLA Navy posture near the shoal."
        ),
        critique_response=(
            "The red team flagged single-source water-cannon claims; two independent wires "
            "(Reuters, AP) corroborate, so the judgment holds."
        ),
        backend="template",
        created_at=now,
    )


def seed() -> None:
    engine = make_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    docs = [
        Document(
            doc_id=f"{label}:demo{i:02d}",
            source=label,
            title=title,
            summary=summary,
            url=f"https://{label}/story/{i}",
            published=now - timedelta(days=days, hours=i),
            credibility=cred,
            ingested_at=now,
        )
        for i, (label, days, cred, title, summary) in enumerate(_ARTICLES)
    ]
    event = Event(
        event_id="evt:demo-shoal",
        title="Coast-guard confrontation at Second Thomas Shoal",
        summary="Multiple sources report a water-cannon incident during a resupply mission.",
        occurred=now - timedelta(days=1),
        doc_count=len(_SHOAL_SOURCES),
        source_count=len(_SHOAL_SOURCES),
        divergence=0.52,  # high-tier wires vs state outlets frame it differently — contested
        created_at=now,
    )
    event_docs = [
        EventDocument(event_id=event.event_id, doc_id=d.doc_id)
        for d in docs
        if d.source in _SHOAL_SOURCES
    ]
    narratives = [
        Narrative(
            narrative_id="nar:demo-external",
            label="'External forces are behind Philippine provocations'",
            summary="A framing pushed largely by state-affiliated outlets attributing the "
            "standoff to US orchestration.",
            doc_count=3,
            source_count=3,
            coordination=0.78,  # bursty + low-reliability-heavy — a human-review flag
            disarm=[
                {
                    "technique_id": "T0002",
                    "name": "Facilitate State Propaganda",
                    "phase": "Execute",
                    "score": 0.41,
                },
                {
                    "technique_id": "T0022",
                    "name": "Leverage Conspiracy Theory Narratives",
                    "phase": "Execute",
                    "score": 0.33,
                },
            ],
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(hours=6),
            created_at=now,
        ),
        Narrative(
            narrative_id="nar:demo-restraint",
            label="Calls for restraint and a code of conduct",
            summary="Wire and regional coverage emphasising de-escalation and diplomacy.",
            doc_count=4,
            source_count=4,
            coordination=0.22,
            disarm=None,
            first_seen=now - timedelta(days=3),
            last_seen=now - timedelta(hours=12),
            created_at=now,
        ),
    ]
    narr_docs = [
        NarrativeDocument(narrative_id="nar:demo-external", doc_id=d.doc_id)
        for d in docs
        if d.source in _EXTERNAL_NARRATIVE_SOURCES
    ]

    with get_session_factory()() as session:
        session.add_all(_sources())
        session.flush()
        session.add_all(docs)
        session.add(event)
        session.add_all(event_docs)
        session.add_all(narratives)
        session.add_all(narr_docs)
        session.add(_brief(now))
        session.commit()

    print(f"seeded demo corpus: {len(docs)} documents, {len(narratives)} narratives, 1 brief")


if __name__ == "__main__":
    seed()
