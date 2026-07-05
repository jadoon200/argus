"""STIX 2.1 export of the influence-operations knowledge graph.

STIX 2.1 is the standard interchange for cyber/threat intelligence (OpenCTI, MISP, TAXII,
the ATT&CK Navigator). Exporting ARGUS's DISARM-keyed narrative graph as STIX makes it
*interoperable* — and joinable with SENTINEL's ATT&CK STIX in the same object model, which is
the whole point of tagging both graphs against parallel technique matrices (see nlp/disarm.py).

The bundle is hand-built (no `stix2` dependency, keeping the zero-cost rule) but conformant:
- DISARM techniques -> `attack-pattern` (external_references to DISARM; `kill_chain_phases`
  carry the DISARM phase, ATT&CK-Navigator style).
- Sources -> `identity` (with the NATO Admiralty reliability in the description).
- Narratives tagged with >=1 DISARM technique -> `report` whose `object_refs` point at those
  techniques ("this narrative is about these influence-ops techniques").

IDs are deterministic (UUIDv5 over a fixed namespace + the object's natural key), so
re-exporting the same graph yields a stable, diffable bundle. Read-only; ARGUS never ingests.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from argus.db.models import Narrative, Source
from argus.nlp.disarm import DISARM_TECHNIQUES, DisarmTechnique

# Fixed namespace for ARGUS STIX ids (deterministic UUIDv5) + a stable timestamp for the
# reference objects (the DISARM catalog and source roster don't have a meaningful "created").
_NS = uuid.UUID("6e1f2c00-0000-4000-8000-a12345678900")
_EPOCH = "2020-01-01T00:00:00.000Z"
_DISARM_URL = "https://github.com/DISARMFoundation/DISARMframeworks"


def _sid(kind: str, key: str) -> str:
    """A deterministic STIX id, e.g. attack-pattern--<uuid5(key)>."""
    return f"{kind}--{uuid.uuid5(_NS, key)}"


def _ts(dt: datetime | None) -> str:
    """RFC3339 UTC with millisecond precision (STIX timestamp format)."""
    if dt is None:
        return _EPOCH
    u = dt.astimezone(UTC)
    return f"{u.strftime('%Y-%m-%dT%H:%M:%S')}.{u.microsecond // 1000:03d}Z"


def _attack_pattern(t: DisarmTechnique) -> dict[str, Any]:
    return {
        "type": "attack-pattern",
        "spec_version": "2.1",
        "id": _sid("attack-pattern", f"disarm:{t.technique_id}"),
        "created": _EPOCH,
        "modified": _EPOCH,
        "name": t.name,
        "description": t.description,
        "external_references": [
            {"source_name": "DISARM", "external_id": t.technique_id, "url": _DISARM_URL}
        ],
        "kill_chain_phases": [{"kill_chain_name": "disarm", "phase_name": t.phase.lower()}],
    }


def _identity(source: Source) -> dict[str, Any]:
    return {
        "type": "identity",
        "spec_version": "2.1",
        "id": _sid("identity", f"source:{source.label}"),
        "created": _EPOCH,
        "modified": _EPOCH,
        "name": source.name or source.label,
        "identity_class": "organization",
        "description": (
            f"Open-source publisher '{source.label}'"
            f"{f' ({source.kind})' if source.kind else ''}; "
            f"NATO Admiralty source reliability {source.reliability}."
        ),
    }


def _report(narrative: Narrative) -> dict[str, Any]:
    """A narrative as a STIX report referencing the DISARM techniques it is tagged with."""
    refs = [
        _sid("attack-pattern", f"disarm:{tag['technique_id']}") for tag in (narrative.disarm or [])
    ]
    return {
        "type": "report",
        "spec_version": "2.1",
        "id": _sid("report", narrative.narrative_id),
        "created": _ts(narrative.created_at),
        "modified": _ts(narrative.created_at),
        "name": narrative.label,
        "report_types": ["threat-report"],
        "published": _ts(narrative.last_seen or narrative.created_at),
        "description": narrative.summary or "",
        "object_refs": refs,  # non-empty: only tagged narratives become reports (see below)
    }


def to_stix_bundle(session: Session) -> dict[str, Any]:
    """Serialize the DISARM-keyed influence-ops graph as a STIX 2.1 bundle."""
    objects: list[dict[str, Any]] = [_attack_pattern(t) for t in DISARM_TECHNIQUES]
    objects += [_identity(s) for s in session.scalars(select(Source).order_by(Source.label)).all()]
    # Only narratives carrying >=1 DISARM technique become reports — STIX requires object_refs
    # to be non-empty, and an untagged narrative has nothing to reference in this bundle.
    for n in session.scalars(select(Narrative).order_by(Narrative.narrative_id)).all():
        if n.disarm:
            objects.append(_report(n))
    return {"type": "bundle", "id": _sid("bundle", "argus-influence-ops"), "objects": objects}
