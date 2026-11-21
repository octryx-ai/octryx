"""What a Workspace's structured graph holds and how its builds went.

Counts per layer from the ledger and the latest builds with their reports (counts and fixed
tokens only), for the admin "Build structured graph" section. Source sync refreshes are on for a
Workspace once it has asked for a structured graph. A running build whose lease ended
(``lease_expired``) has no live claimer: its runner stopped (a restart) or handed it back, and the
next claim resumes it.

The counts cover every source, restricted ones included, so only the Workspace's authors (the
roles that may request a build) see them; any other reader gets the build states without counts
or reports (``counts_visible: false``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import BackgroundWorkerRunState
from ....models.project.knowledge_structured import (
    KnowledgeStructuredBuild,
    KnowledgeStructuredEdge,
    KnowledgeStructuredExtraction,
    KnowledgeStructuredNode,
)
from ....time_utils import utc_now
from ..access.authorization import AuthorizedWorkspace
from .build_runner import RUNNER_NAME
from .profile_types import LAYERS
from .workspace_profile import workspace_profile_id

MAX_BUILDS = 5


async def _runner_health(db: AsyncSession) -> dict[str, Any] | None:
    """The runner's last recorded run: state, times, counts and a fixed failure token (no owner, no text)."""
    row = await db.get(BackgroundWorkerRunState, RUNNER_NAME)
    if row is None:
        return None
    return {"status": row.status, "completed_at": _iso(row.completed_at), "updated_at": _iso(row.updated_at),
            "failure": row.error if row.status == "failed" else None, "run_count": int(row.run_count or 0),
            "failure_count": int(row.failure_count or 0)}


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _counts(db: AsyncSession, model, project_id: str, profile_id: str) -> dict[str, int]:
    rows = await db.execute(
        select(model.layer, func.count()).where(model.project_id == project_id, model.profile == profile_id)
        .group_by(model.layer)
    )
    return {str(layer): int(count) for layer, count in rows.all()}


async def structured_status(db: AsyncSession, *, authorized: AuthorizedWorkspace) -> dict[str, Any]:
    project_id = authorized.project_id
    profile_id = await workspace_profile_id(db, project_id)
    counts_visible = authorized.may_author
    layers = None
    if counts_visible:
        revisions = await _counts(db, KnowledgeStructuredExtraction, project_id, profile_id)
        nodes = await _counts(db, KnowledgeStructuredNode, project_id, profile_id)
        edges = await _counts(db, KnowledgeStructuredEdge, project_id, profile_id)
        layers = {layer: {"revisions": revisions.get(layer, 0), "nodes": nodes.get(layer, 0),
                          "edges": edges.get(layer, 0)} for layer in LAYERS}
    now = utc_now()
    builds = (await db.execute(
        select(KnowledgeStructuredBuild)
        .where(KnowledgeStructuredBuild.project_id == project_id)
        .order_by(KnowledgeStructuredBuild.requested_at.desc())
        .limit(MAX_BUILDS)
    )).scalars().all()
    return {
        "workspace_id": project_id,
        "profile": profile_id,
        "counts_visible": counts_visible,
        "layers": layers,
        "refresh_after_sync": bool(builds),
        "runner": await _runner_health(db),
        "builds": [
            {"id": build.id, "state": build.state, "trigger": build.trigger, "layers": list(build.layers),
             "profile": build.profile, "requested_at": _iso(build.requested_at), "started_at": _iso(build.started_at),
             "finished_at": _iso(build.finished_at), "failure": build.failure,
             "lease_expired": build.state == "running" and (build.lease_until is None or build.lease_until < now),
             "report": (build.report or {}) if counts_visible else None}
            for build in builds
        ],
    }


__all__ = ["structured_status"]
