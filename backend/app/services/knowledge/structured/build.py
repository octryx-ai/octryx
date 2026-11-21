"""Structured graph builds: requested per Workspace, claimed with a lease, run in bounded slices.

A build names the layers to (re)build. :func:`request_build` merges a request into the Workspace's
pending build, so repeated clicks or several source syncs never queue duplicates; a manual request
makes the merged build manual. The merge is a conditional ``UPDATE`` on ``state = pending``: a build
a runner claimed in between is never changed, the request then starts a new pending build.

A manual request for a Workspace whose source-sync refresh is **running** takes that build over
instead of queuing behind it (:func:`request_build`): the running build becomes manual with the
merged layers. The projection worker hands a cooperative build back after every slice (lease ends
now), so the manual runner claims it as soon as the slice in flight commits; nothing waits for a
lease to expire.

Who runs a build depends on its trigger: a source-sync refresh is cooperative (the projection worker
claims one due build per tick, :func:`run_next_build` with :data:`COOPERATIVE_TRIGGERS`, and runs
one slice of it), a manual build has its own runner (``build_runner.py``) that runs short slices
back to back. A slice (``build_slice.py``) extracts per layer what the ledger does not hold yet and
then links; the next slice continues where the ledger says. No step calls a model.

A source sync requests only the layers its connector kind feeds (:func:`sync_layers`).

The report holds counts and fixed warning tokens only, never source text or values.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ....models.project.knowledge_structured import KnowledgeStructuredBuild
from ....time_utils import utc_now
from ..runtime import EvidenceRuntime
from .build_slice import run_build_slice
from .build_states import (
    COOPERATIVE_TRIGGERS,
    FAILURE_BUILD,
    LEASE_SECONDS,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    TRIGGER_MANUAL,
    TRIGGER_SOURCE_SYNC,
)
from .profile_types import (
    LAYER_CONFIGURATION,
    LAYER_MANUAL,
    LAYER_OPERATIONS,
    LAYERS,
    StructuredProfile,
    StructuredProfileError,
)
from .workspace_profile import workspace_profile, workspace_profile_id

logger = logging.getLogger(__name__)

# A request re-reads and retries when a concurrent request or claim changed the build it merged into.
MAX_MERGE_ATTEMPTS = 5


class StructuredBuildRequestError(ValueError):
    """The request names no layer, or a layer the profile does not know."""


def normalize_layers(layers: object) -> list[str]:
    if not isinstance(layers, (list, tuple)) or not layers or not all(isinstance(item, str) for item in layers):
        raise StructuredBuildRequestError()
    if not set(layers) <= set(LAYERS):
        raise StructuredBuildRequestError()
    return [layer for layer in LAYERS if layer in layers]


async def _merge_target(db: AsyncSession, project_id: str, trigger: str) -> tuple[str, str, str, list[str]] | None:
    """The build a request merges into, as read now: ``(id, state, trigger, layers)``.

    A manual request takes over the Workspace's running source-sync refresh, so it never queues
    behind it; otherwise (and for any other request) the Workspace's pending build.
    """
    rows = (
        await db.execute(
            select(
                KnowledgeStructuredBuild.id, KnowledgeStructuredBuild.state, KnowledgeStructuredBuild.trigger,
                KnowledgeStructuredBuild.layers,
            )
            .where(
                KnowledgeStructuredBuild.project_id == project_id,
                KnowledgeStructuredBuild.state.in_((STATE_PENDING, STATE_RUNNING)),
            )
            .order_by(KnowledgeStructuredBuild.requested_at)
        )
    ).all()
    if trigger == TRIGGER_MANUAL:
        running = [row for row in rows if row.state == STATE_RUNNING and row.trigger in COOPERATIVE_TRIGGERS]
        if running:
            return tuple(running[0])
    return next((tuple(row) for row in rows if row.state == STATE_PENDING), None)


async def request_build(
    db: AsyncSession, *, project_id: str, layers: object, trigger: str, requested_by: str | None = None
) -> KnowledgeStructuredBuild:
    wanted = normalize_layers(layers)
    for _ in range(MAX_MERGE_ATTEMPTS):
        target = await _merge_target(db, project_id, trigger)
        if target is None:
            break
        build_id, state, target_trigger, target_layers = target
        values: dict = {"layers": [layer for layer in LAYERS if layer in set(target_layers or ()) | set(wanted)],
                        "profile": await workspace_profile_id(db, project_id)}
        if trigger == TRIGGER_MANUAL:
            values["trigger"] = TRIGGER_MANUAL
        # Conditional on what was read: a build claimed (or taken over) since then is left alone.
        merged = await db.execute(
            update(KnowledgeStructuredBuild)
            .where(
                KnowledgeStructuredBuild.id == build_id,
                KnowledgeStructuredBuild.state == state,
                KnowledgeStructuredBuild.trigger == target_trigger,
            )
            .values(**values)
        )
        await db.commit()
        if merged.rowcount == 1:
            build = await db.get(KnowledgeStructuredBuild, build_id, populate_existing=True)
            # A concurrent merge may have written its own layer list over ours: then merge again.
            if build is not None and set(wanted) <= set(build.layers):
                return build
    build = KnowledgeStructuredBuild(
        project_id=project_id, profile=await workspace_profile_id(db, project_id), layers=wanted, trigger=trigger,
        state=STATE_PENDING, requested_by=requested_by, requested_at=utc_now(), report={},
    )
    db.add(build)
    await db.commit()
    return build


async def has_built(db: AsyncSession, project_id: str) -> bool:
    """Whether the Workspace ever asked for a structured graph (source syncs refresh only those)."""
    found = await db.execute(
        select(KnowledgeStructuredBuild.id).where(KnowledgeStructuredBuild.project_id == project_id).limit(1)
    )
    return found.first() is not None


def sync_layers(profile: StructuredProfile, connector_kind: str | None) -> list[str]:
    """The layers a sync of ``connector_kind`` can change, from the profile's connector kinds.

    Configuration kinds feed the configuration layer, operations kinds (ServiceNow, Jira, the
    Kubernetes inventory) the operations layer; any other kind brings documents and refreshes the
    manual layer (PDF manuals) and the operations layer. An unknown sync (``None``) refreshes every
    layer.
    """
    if connector_kind is None:
        return list(LAYERS)
    layers = set()
    if connector_kind in profile.config_connector_kinds:
        layers.add(LAYER_CONFIGURATION)
    if connector_kind in profile.ops_connector_kinds:
        layers.add(LAYER_OPERATIONS)
    if not layers:
        layers = {LAYER_MANUAL, LAYER_OPERATIONS}
    return [layer for layer in LAYERS if layer in layers]


async def refresh_after_sync(db: AsyncSession, project_id: str, connector_kind: str | None = None) -> None:
    """A completed source sync refreshes the affected layers of a Workspace that has a structured graph."""
    if await has_built(db, project_id):
        try:
            layers = sync_layers(await workspace_profile(db, project_id), connector_kind)
        except StructuredProfileError:
            # A stored profile the loader now refuses: refresh everything; the build reports the failure.
            layers = list(LAYERS)
        await request_build(db, project_id=project_id, layers=layers, trigger=TRIGGER_SOURCE_SYNC)


def _due(now):
    return or_(
        KnowledgeStructuredBuild.state == STATE_PENDING,
        and_(KnowledgeStructuredBuild.state == STATE_RUNNING, KnowledgeStructuredBuild.lease_until < now),
    )


async def claim_next_build(
    db: AsyncSession, *, worker_id: str, triggers: tuple[str, ...] | None = None, lease_seconds: float = LEASE_SECONDS
) -> str | None:
    """Claim the oldest due build (of ``triggers`` only, when given) whose Workspace runs no other build.

    The lease is how long the build stays the claimer's without a renewal; a claimer that dies
    (a restart) leaves it ``running`` until then, after which the next claim resumes it.
    """
    now = utc_now()
    due = _due(now) if triggers is None else and_(_due(now), KnowledgeStructuredBuild.trigger.in_(triggers))
    candidates = (
        await db.execute(
            select(KnowledgeStructuredBuild.id, KnowledgeStructuredBuild.project_id)
            .where(due)
            .order_by(KnowledgeStructuredBuild.requested_at)
            .limit(10)
        )
    ).all()
    for build_id, project_id in candidates:
        busy = await db.execute(
            select(KnowledgeStructuredBuild.id).where(
                KnowledgeStructuredBuild.project_id == project_id,
                KnowledgeStructuredBuild.id != build_id,
                KnowledgeStructuredBuild.state == STATE_RUNNING,
            )
        )
        if busy.first() is not None:
            continue
        claimed = await db.execute(
            update(KnowledgeStructuredBuild)
            .where(KnowledgeStructuredBuild.id == build_id, _due(now))
            .values(state=STATE_RUNNING, claimed_by=worker_id[:120], lease_until=now + timedelta(seconds=lease_seconds))
        )
        await db.commit()
        if claimed.rowcount == 1:
            return build_id
    return None


async def hand_back(db: AsyncSession, build_id: str, worker_id: str) -> None:
    """End this worker's lease now, so the next claim resumes the build (a takeover's runner at once)."""
    await db.execute(
        update(KnowledgeStructuredBuild)
        .where(
            KnowledgeStructuredBuild.id == build_id,
            KnowledgeStructuredBuild.state == STATE_RUNNING,
            KnowledgeStructuredBuild.claimed_by == worker_id[:120],
        )
        .values(lease_until=utc_now())
    )
    await db.commit()


async def fail_build(db: AsyncSession, build_id: str, worker_id: str | None = None) -> str:
    """A slice raised: roll back and fail the build with the fixed token (never the error text).

    With ``worker_id`` only while that worker still holds the build: a slice that lost its lease
    never fails the build its new owner runs.
    """
    await db.rollback()
    logger.warning("Structured knowledge graph build failed: build=%s", build_id)
    held = [] if worker_id is None else [KnowledgeStructuredBuild.claimed_by == worker_id[:120]]
    await db.execute(
        update(KnowledgeStructuredBuild)
        .where(KnowledgeStructuredBuild.id == build_id, KnowledgeStructuredBuild.state == STATE_RUNNING, *held)
        .values(state=STATE_FAILED, failure=FAILURE_BUILD, finished_at=utc_now(), lease_until=None)
    )
    await db.commit()
    return STATE_FAILED


async def run_next_build(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    runtime: EvidenceRuntime | None,
    worker_id: str,
    triggers: tuple[str, ...] | None = None,
) -> str | None:
    """Claim and run one slice of the next due build, then hand it back; a failure fails it with a fixed token."""
    async with session_factory() as db:
        build_id = await claim_next_build(db, worker_id=worker_id, triggers=triggers)
        if build_id is None:
            return None
        try:
            state = await run_build_slice(db, runtime=runtime, build_id=build_id, worker_id=worker_id)
        except Exception:
            return await fail_build(db, build_id, worker_id)
        if state == STATE_RUNNING:
            # Never hold a lease between ticks: a manual takeover's runner claims the build at once.
            await hand_back(db, build_id, worker_id)
        return state


__all__ = [
    "StructuredBuildRequestError",
    "claim_next_build",
    "fail_build",
    "hand_back",
    "has_built",
    "normalize_layers",
    "refresh_after_sync",
    "request_build",
    "run_next_build",
    "sync_layers",
]
