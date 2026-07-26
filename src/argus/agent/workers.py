"""Lean domain workers and the all-source fusion orchestrator.

Workers gather deterministically and return the existing ``EvidenceItem`` contract. They do
not run their own LLMs: one central quick/panel synthesis consumes the fused evidence, keeping
memory at one model and latency close to the pre-fusion path.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import ClassVar, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from argus.agent.state import EvidenceItem
from argus.agent.supervisor import ALL_LANES, LANE_ORDER, Lane, route_domains
from argus.bridge.geoint import GeointBridge, ocean_evidence, sky_evidence
from argus.bridge.sentinel import SentinelBridge, cyber_evidence
from argus.config import Settings, get_settings
from argus.db.models import Document, Source
from argus.logging import get_logger

log = get_logger(__name__)

OsintGatherer = Callable[[Session, str, int], list[EvidenceItem]]


@dataclass(frozen=True)
class WorkerStatus:
    lane: Lane
    label: str
    configured: bool
    reachable: bool
    count: int | None
    count_label: str
    last_item: EvidenceItem | None = None
    detail: str | None = None


@dataclass(frozen=True)
class FusionGather:
    evidence: list[EvidenceItem]
    lanes_consulted: list[Lane]
    reason: str
    lane_counts: dict[Lane, int]


class DomainWorker(Protocol):
    lane: ClassVar[Lane]

    def gather(self, query: str, limit: int) -> list[EvidenceItem]: ...

    def status(self) -> WorkerStatus: ...


def _int_stat(stats: dict[str, object] | None, key: str) -> int | None:
    if stats is None:
        return None
    value = stats.get(key)
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class OsintWorker:
    session: Session
    gatherer: OsintGatherer
    lane: ClassVar[Lane] = "osint"

    def gather(self, query: str, limit: int) -> list[EvidenceItem]:
        return self.gatherer(self.session, query, limit)

    def status(self) -> WorkerStatus:
        count = self.session.scalar(select(func.count()).select_from(Document)) or 0
        latest = self.session.scalar(
            select(Document)
            .order_by(Document.published.desc().nulls_last(), Document.ingested_at.desc())
            .limit(1)
        )
        item: EvidenceItem | None = None
        if latest is not None:
            source = self.session.get(Source, latest.source)
            item = EvidenceItem(
                doc_id=latest.doc_id,
                title=latest.title,
                source=latest.source,
                reliability=source.reliability if source else "F",
                credibility=latest.credibility,
                summary=latest.summary,
                published=latest.published.isoformat() if latest.published else None,
                url=latest.url,
            )
        return WorkerStatus(
            lane=self.lane,
            label="Open-source reporting",
            configured=True,
            reachable=True,
            count=count,
            count_label="documents",
            last_item=item,
            detail="GDELT global news + curated agency RSS",
        )


@dataclass(frozen=True)
class SkyWorker:
    settings: Settings
    lane: ClassVar[Lane] = "sky"

    def gather(self, query: str, limit: int) -> list[EvidenceItem]:
        return sky_evidence(self.settings, limit=limit, query=query)

    def status(self) -> WorkerStatus:
        if not self.settings.horus_api_url:
            return WorkerStatus(self.lane, "Sky / HORUS", False, False, None, "incidents")
        bridge = GeointBridge(
            self.settings.horus_api_url, "sky-geoint", self.settings.http_timeout_seconds
        )
        reachable = bridge.available()
        stats = bridge.stats() if reachable else None
        items = bridge.incidents_as_evidence(limit=1) if reachable else []
        return WorkerStatus(
            self.lane,
            "Sky / HORUS",
            True,
            reachable,
            _int_stat(stats, "incidents"),
            "incidents",
            items[0] if items else None,
            "ADS-B air-domain awareness + GNSS-interference detection",
        )


@dataclass(frozen=True)
class OceanWorker:
    settings: Settings
    lane: ClassVar[Lane] = "ocean"

    def gather(self, query: str, limit: int) -> list[EvidenceItem]:
        return ocean_evidence(self.settings, limit=limit, query=query)

    def status(self) -> WorkerStatus:
        if not self.settings.pharos_api_url:
            return WorkerStatus(self.lane, "Ocean / PHAROS", False, False, None, "incidents")
        bridge = GeointBridge(
            self.settings.pharos_api_url, "ocean-geoint", self.settings.http_timeout_seconds
        )
        reachable = bridge.available()
        stats = bridge.stats() if reachable else None
        items = bridge.incidents_as_evidence(limit=1) if reachable else []
        return WorkerStatus(
            self.lane,
            "Ocean / PHAROS",
            True,
            reachable,
            _int_stat(stats, "incidents"),
            "incidents",
            items[0] if items else None,
            "AIS maritime-domain awareness",
        )


@dataclass(frozen=True)
class CyberWorker:
    settings: Settings
    lane: ClassVar[Lane] = "cyber"

    def gather(self, query: str, limit: int) -> list[EvidenceItem]:
        return cyber_evidence(self.settings, limit=limit, query=query)

    def status(self) -> WorkerStatus:
        if not self.settings.sentinel_api_url:
            return WorkerStatus(self.lane, "Cyber / SENTINEL", False, False, None, "campaigns")
        bridge = SentinelBridge(self.settings.sentinel_api_url, self.settings.http_timeout_seconds)
        reachable = bridge.available()
        stats = bridge.stats() if reachable else None
        items = bridge.campaigns_as_evidence(limit=1) if reachable else []
        return WorkerStatus(
            self.lane,
            "Cyber / SENTINEL",
            True,
            reachable,
            _int_stat(stats, "campaigns"),
            "campaigns",
            items[0] if items else None,
            "Read-only cyber campaign + ATT&CK knowledge graph",
        )


def build_workers(
    session: Session, gatherer: OsintGatherer, settings: Settings | None = None
) -> dict[Lane, DomainWorker]:
    active = settings or get_settings()
    return {
        "osint": OsintWorker(session, gatherer),
        "sky": SkyWorker(active),
        "ocean": OceanWorker(active),
        "cyber": CyberWorker(active),
    }


def gather_fused_evidence(
    session: Session,
    query: str,
    osint_limit: int,
    gatherer: OsintGatherer,
    settings: Settings | None = None,
    lane_limit: int = 5,
) -> FusionGather:
    """Route, dispatch selected workers, fuse their evidence, and de-duplicate by doc id."""
    active = settings or get_settings()
    if active.fusion_supervisor:
        planned, reason = route_domains(query)
    else:
        planned = set(ALL_LANES)
        reason = "fusion supervisor disabled — consulted every lane (legacy flat fusion)"

    workers = build_workers(session, gatherer, active)
    by_lane: dict[Lane, list[EvidenceItem]] = {}
    counts: dict[Lane, int] = {}
    consulted = [lane for lane in LANE_ORDER if lane in planned]
    for lane in consulted:
        limit = osint_limit if lane == "osint" else lane_limit
        try:
            items = workers[lane].gather(query, limit)
        except Exception as exc:
            if lane == "osint":
                raise
            log.warning("fusion_worker_failed", lane=lane, error=str(exc))
            items = []
        counts[lane] = len(items)
        by_lane[lane] = items

    # Round-robin the selected lanes so a large OSINT corpus cannot bury every sibling
    # item below a fallback/model context cut. This is source-domain diversity, analogous
    # to gather_evidence's per-publisher cap: each consulted lane gets an early voice.
    fused: list[EvidenceItem] = []
    max_lane_items = max((len(items) for items in by_lane.values()), default=0)
    for index in range(max_lane_items):
        for lane in consulted:
            items = by_lane[lane]
            if index < len(items):
                fused.append(items[index])

    seen: set[str] = set()
    unique: list[EvidenceItem] = []
    for item in fused:
        if item.doc_id not in seen:
            seen.add(item.doc_id)
            unique.append(item)
    return FusionGather(unique, consulted, reason, counts)


def overview_statuses(
    session: Session, gatherer: OsintGatherer, settings: Settings | None = None
) -> list[WorkerStatus]:
    """One cached-dashboard snapshot per lane; remote checks fan out concurrently."""
    workers = build_workers(session, gatherer, settings)
    statuses: dict[Lane, WorkerStatus] = {"osint": workers["osint"].status()}
    remote: tuple[Lane, ...] = ("sky", "ocean", "cyber")
    with ThreadPoolExecutor(max_workers=len(remote), thread_name_prefix="argus-overview") as pool:
        futures = {lane: pool.submit(workers[lane].status) for lane in remote}
        for lane, future in futures.items():
            try:
                statuses[lane] = future.result()
            except Exception as exc:
                log.warning("overview_worker_failed", lane=lane, error=str(exc))
                statuses[lane] = WorkerStatus(
                    lane, lane.title(), True, False, None, "items", detail="status check failed"
                )
    return [statuses[lane] for lane in LANE_ORDER]
