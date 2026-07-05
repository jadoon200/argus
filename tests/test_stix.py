from datetime import UTC, datetime

from sqlalchemy.orm import Session

from argus.db.models import Narrative, Source
from argus.nlp.disarm import DISARM_TECHNIQUES
from argus.stix import _sid, to_stix_bundle


def _tagged_narrative() -> Narrative:
    return Narrative(
        narrative_id="nar:abc",
        label="Sabotage narrative",
        summary="coordinated claims of foreign sabotage",
        doc_count=3,
        source_count=1,
        coordination=0.8,
        disarm=[
            {
                "technique_id": "T0022",
                "name": "Leverage Conspiracy Theory Narratives",
                "phase": "Execute",
                "score": 0.4,
            },
            {
                "technique_id": "T0049",
                "name": "Flood Information Space",
                "phase": "Execute",
                "score": 0.3,
            },
        ],
        first_seen=datetime(2026, 6, 20, tzinfo=UTC),
        last_seen=datetime(2026, 6, 21, tzinfo=UTC),
    )


def test_bundle_structure_and_refs(session: Session) -> None:
    session.add(Source(label="rt.com", name="RT", kind="state", reliability="D"))
    session.add(_tagged_narrative())
    session.flush()

    bundle = to_stix_bundle(session)
    assert bundle["type"] == "bundle" and bundle["id"].startswith("bundle--")
    objs = bundle["objects"]
    assert all(o["spec_version"] == "2.1" for o in objs)
    assert {"attack-pattern", "identity", "report"} <= {o["type"] for o in objs}

    # Every DISARM technique is exported as an attack-pattern with a DISARM external reference.
    aps = [o for o in objs if o["type"] == "attack-pattern"]
    assert len(aps) == len(DISARM_TECHNIQUES)
    flood = next(o for o in aps if o["name"] == "Flood Information Space")
    assert flood["external_references"][0] == {
        "source_name": "DISARM",
        "external_id": "T0049",
        "url": "https://github.com/DISARMFoundation/DISARMframeworks",
    }
    assert flood["kill_chain_phases"][0]["kill_chain_name"] == "disarm"

    # The source becomes an identity carrying its Admiralty reliability.
    ident = next(o for o in objs if o["type"] == "identity")
    assert "reliability D" in ident["description"]

    # The narrative becomes a report referencing exactly its two tagged techniques (resolvable).
    report = next(o for o in objs if o["type"] == "report")
    assert report["name"] == "Sabotage narrative"
    assert report["object_refs"]  # STIX requires object_refs to be non-empty
    assert set(report["object_refs"]) == {
        _sid("attack-pattern", "disarm:T0022"),
        _sid("attack-pattern", "disarm:T0049"),
    }
    assert set(report["object_refs"]) <= {o["id"] for o in aps}  # every ref resolves in-bundle


def test_untagged_narrative_is_not_a_report(session: Session) -> None:
    session.add(
        Narrative(narrative_id="nar:x", label="plain", doc_count=3, source_count=1, disarm=None)
    )
    session.flush()
    assert not any(o["type"] == "report" for o in to_stix_bundle(session)["objects"])


def test_bundle_ids_are_deterministic(session: Session) -> None:
    session.add(Source(label="bbc-world", reliability="B"))
    session.add(_tagged_narrative())
    session.flush()
    assert to_stix_bundle(session) == to_stix_bundle(session)  # stable + diffable
