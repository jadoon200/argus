"""Seed a demo corpus for a public deployment — deterministic, no ML stack, no network.

The free single-container demo pins ``ARGUS_LLM_BACKEND=template`` and runs on a SQLite file,
so a fresh deploy would otherwise start empty. This bakes a small, realistic corpus across the
three topics the dashboard offers as examples (South China Sea, the Sahel, the edge-VPN
exploitation wave), so every example question returns a real cited brief on first load — with
rated sources, corroborated events, coordination-scored narratives, and one worked brief. Every
source carries its genuine NATO-Admiralty grade from ``argus.sources``.

    ARGUS_DATABASE_URL=sqlite:////app/data/argus.db python scripts/seed_demo.py

Idempotent by construction: it drops and recreates the tables each run. Safe to run at
image-build time (baked into the container) or against a mounted volume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


@dataclass(frozen=True)
class Art:
    """One demo article. `days`/`cred` = published-days-ago and Admiralty credibility."""

    domain: str
    days: int
    cred: int
    title: str
    summary: str


@dataclass(frozen=True)
class Narr:
    """A demo narrative over a subset of a topic's source domains."""

    nid: str
    label: str
    summary: str
    coordination: float
    domains: set[str]
    disarm: list[dict[str, object]] | None = None


@dataclass(frozen=True)
class Ev:
    """A demo event (corroborated cluster) over a subset of a topic's source domains."""

    eid: str
    title: str
    summary: str
    divergence: float
    domains: set[str]


@dataclass(frozen=True)
class Topic:
    key: str
    articles: list[Art]
    events: list[Ev] = field(default_factory=list)
    narratives: list[Narr] = field(default_factory=list)


_DISARM_STATE = [
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
]

TOPICS: list[Topic] = [
    Topic(
        key="scs",
        articles=[
            Art(
                "reuters.com",
                1,
                3,
                "Chinese coast guard shadows Philippine resupply run near Second Thomas Shoal",
                "China Coast Guard vessels tracked a resupply mission to the grounded BRP Sierra "
                "Madre; a water cannon was deployed against a supply boat, Manila said.",
            ),
            Art(
                "apnews.com",
                1,
                3,
                "Manila protests 'aggressive' Chinese maneuvers in South China Sea standoff",
                "The Philippines lodged a diplomatic protest over what it called dangerous "
                "blocking maneuvers by Chinese vessels during a routine resupply.",
            ),
            Art(
                "bbc.com",
                2,
                2,
                "South China Sea: what is behind the Philippines-China flare-up?",
                "Analysis of why the Second Thomas Shoal has become a flashpoint in the wider "
                "maritime dispute over competing sovereignty claims.",
            ),
            Art(
                "channelnewsasia.com",
                2,
                2,
                "ASEAN urges restraint as South China Sea tensions rise",
                "The regional bloc called for de-escalation and progress on a binding code of "
                "conduct after the latest coast-guard confrontation.",
            ),
            Art(
                "scmp.com",
                1,
                2,
                "Beijing says Philippine vessels 'intruded' into Chinese waters",
                "China's foreign ministry defended the coast-guard action as lawful enforcement "
                "within its claimed nine-dash-line jurisdiction.",
            ),
            Art(
                "cnn.com",
                3,
                3,
                "US reaffirms defense-treaty commitment to the Philippines",
                "Washington restated that the mutual defense treaty covers armed attacks on "
                "Philippine vessels in the South China Sea.",
            ),
            Art(
                "rt.com",
                1,
                1,
                "West stoking tensions in South China Sea, Beijing says",
                "State outlet frames the standoff as a US-orchestrated provocation aimed at "
                "containing China's rise in the region.",
            ),
            Art(
                "globaltimes.cn",
                1,
                1,
                "Philippine 'provocations' in South China Sea backed by external forces",
                "State-affiliated commentary attributes the confrontation to Washington's "
                "encouragement of Manila.",
            ),
        ],
        events=[
            Ev(
                "evt:demo-shoal",
                "Coast-guard confrontation at Second Thomas Shoal",
                "Multiple sources report a water-cannon incident during a resupply mission.",
                0.52,
                {"reuters.com", "apnews.com", "scmp.com", "rt.com", "globaltimes.cn", "cnn.com"},
            ),
        ],
        narratives=[
            Narr(
                "nar:demo-external",
                "'External forces are behind Philippine provocations'",
                "A framing pushed largely by state-affiliated outlets attributing the standoff "
                "to US orchestration.",
                0.78,
                {"rt.com", "globaltimes.cn", "scmp.com"},
                _DISARM_STATE,
            ),
            Narr(
                "nar:demo-restraint",
                "Calls for restraint and a code of conduct",
                "Wire and regional coverage emphasising de-escalation and diplomacy.",
                0.22,
                {"reuters.com", "apnews.com", "channelnewsasia.com", "cnn.com"},
            ),
        ],
    ),
    Topic(
        key="sahel",
        articles=[
            Art(
                "reuters.com",
                2,
                3,
                "Sahel juntas deepen security pact as jihadist violence spreads",
                "Military governments in the Sahel tightened a mutual-defence pact as attacks by "
                "armed groups pushed instability across the region's borderlands.",
            ),
            Art(
                "apnews.com",
                2,
                3,
                "Jihadist attacks displace thousands across the Sahel",
                "A wave of assaults on villages and garrisons has driven fresh displacement, "
                "deepening a humanitarian and security crisis in the central Sahel.",
            ),
            Art(
                "bbc.com",
                3,
                2,
                "What is driving instability across the Sahel?",
                "Analysis of the coups, insurgencies and foreign-influence competition behind "
                "the Sahel's spiral of instability.",
            ),
            Art(
                "aljazeera.com",
                2,
                2,
                "Sahel states pivot away from Western partners amid insecurity",
                "Sahel governments have expelled some Western forces and courted new security "
                "partners as insurgent violence rises.",
            ),
            Art(
                "rt.com",
                2,
                1,
                "Western withdrawal leaves Sahel to sort out its own security, Moscow says",
                "State outlet frames the Sahel's realignment as a rejection of failed Western "
                "intervention and an opening for new partners.",
            ),
        ],
        events=[
            Ev(
                "evt:demo-sahel",
                "Coordinated jihadist assaults across the central Sahel",
                "Wire services report a spate of near-simultaneous attacks driving displacement.",
                0.31,
                {"reuters.com", "apnews.com", "bbc.com"},
            ),
        ],
        narratives=[
            Narr(
                "nar:demo-sahel-west",
                "'Western interference is to blame for Sahel instability'",
                "A realignment framing amplified by state-affiliated outlets casting Western "
                "partners as the cause of the crisis.",
                0.61,
                {"rt.com", "aljazeera.com"},
                [_DISARM_STATE[0]],
            ),
        ],
    ),
    Topic(
        key="cyber",
        articles=[
            Art(
                "reuters.com",
                1,
                3,
                "Wave of edge-VPN exploitation hits enterprises worldwide",
                "Security agencies warned of mass exploitation of edge VPN appliances, with "
                "attackers chaining vulnerabilities to breach corporate networks.",
            ),
            Art(
                "bbc.com",
                1,
                2,
                "Edge VPN devices targeted in global exploitation wave, researchers say",
                "Researchers linked the edge-VPN exploitation wave to a capable actor probing "
                "unpatched gateways across multiple countries.",
            ),
            Art(
                "apnews.com",
                2,
                2,
                "Governments urge urgent patching after edge-VPN exploitation spree",
                "National cyber agencies issued advisories urging organisations to patch edge "
                "VPN gateways being actively exploited in the wild.",
            ),
            Art(
                "cnn.com",
                2,
                2,
                "Who is behind the edge-VPN exploitation wave? Attribution stays contested",
                "Analysts weigh state-linked and criminal explanations for the edge-VPN "
                "campaign; open reporting attributes it only tentatively.",
            ),
        ],
        events=[
            Ev(
                "evt:demo-vpn",
                "Mass exploitation of edge-VPN appliances",
                "Multiple wires and agencies report coordinated exploitation of VPN gateways.",
                0.18,
                {"reuters.com", "bbc.com", "apnews.com", "cnn.com"},
            ),
        ],
    ),
]


def _all_domains() -> set[str]:
    return {a.domain for t in TOPICS for a in t.articles}


def _sources() -> list[Source]:
    rows = []
    for label in sorted(_all_domains()):
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
        citations=["reuters.com:scs00", "apnews.com:scs01", "cnn.com:scs05", "rt.com:scs06"],
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


def _snapshot_briefs(now: datetime) -> list[Brief]:
    """Precomputed full-panel briefs for the dashboard's example questions, generated
    locally with a real model OVER THIS SAME SEED CORPUS (see export_seed_briefs.py) so
    their citations resolve to seed doc ids. The model-less cloud deploy serves these via
    the dashboard's snapshot path — honestly labelled, since the deploy can't produce a
    deliberated product live. Missing file -> no snapshots, everything else still works."""
    path = Path(__file__).with_name("seed_briefs.json")
    if not path.exists():
        return []
    rows: list[dict[str, object]] = json.loads(path.read_text())
    return [Brief(**row, created_at=now) for row in rows]  # type: ignore[arg-type]


def seed() -> None:
    engine = make_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    docs: list[Document] = []
    doc_by_key: dict[tuple[str, str], str] = {}  # (topic, domain) -> doc_id (for edges)
    events: list[Event] = []
    event_docs: list[EventDocument] = []
    narratives: list[Narrative] = []
    narr_docs: list[NarrativeDocument] = []

    for topic in TOPICS:
        for i, a in enumerate(topic.articles):
            doc_id = f"{a.domain}:{topic.key}{i:02d}"
            doc_by_key[(topic.key, a.domain)] = doc_id
            docs.append(
                Document(
                    doc_id=doc_id,
                    source=a.domain,
                    title=a.title,
                    summary=a.summary,
                    url=f"https://{a.domain}/{topic.key}/{i}",
                    published=now - timedelta(days=a.days, hours=i),
                    credibility=a.cred,
                    ingested_at=now,
                )
            )
        for ev in topic.events:
            members = [d for d in topic.articles if d.domain in ev.domains]
            events.append(
                Event(
                    event_id=ev.eid,
                    title=ev.title,
                    summary=ev.summary,
                    occurred=now - timedelta(days=1),
                    doc_count=len(members),
                    source_count=len({m.domain for m in members}),
                    divergence=ev.divergence,
                    created_at=now,
                )
            )
            event_docs += [
                EventDocument(event_id=ev.eid, doc_id=doc_by_key[(topic.key, m.domain)])
                for m in members
            ]
        for nr in topic.narratives:
            members = [d for d in topic.articles if d.domain in nr.domains]
            narratives.append(
                Narrative(
                    narrative_id=nr.nid,
                    label=nr.label,
                    summary=nr.summary,
                    doc_count=len(members),
                    source_count=len({m.domain for m in members}),
                    coordination=nr.coordination,
                    disarm=nr.disarm,
                    first_seen=now - timedelta(days=3),
                    last_seen=now - timedelta(hours=6),
                    created_at=now,
                )
            )
            narr_docs += [
                NarrativeDocument(narrative_id=nr.nid, doc_id=doc_by_key[(topic.key, m.domain)])
                for m in members
            ]

    with get_session_factory()() as session:
        session.add_all(_sources())
        session.flush()
        session.add_all(docs)
        session.add_all(events)
        session.add_all(event_docs)
        session.add_all(narratives)
        session.add_all(narr_docs)
        session.add(_brief(now))
        snapshots = _snapshot_briefs(now)
        session.add_all(snapshots)
        session.commit()

    print(
        f"seeded demo corpus: {len(docs)} documents across {len(TOPICS)} topics, "
        f"{len(events)} events, {len(narratives)} narratives, "
        f"{1 + len(snapshots)} briefs ({len(snapshots)} model snapshots)"
    )


if __name__ == "__main__":
    seed()
