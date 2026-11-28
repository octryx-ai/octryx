"""The linkage phase of a structured build: inside the slice deadline, resumable, only where needed."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_structured import KnowledgeStructuredBuild
from .layers import BuildContext, LayerSpec
from .profile_types import LAYERS

LINK_DEPENDS = {"configuration": {"manual"}}
STATE_PARTIAL = "partial"
STATE_UNCHANGED = "unchanged"
_UNSETTLED = frozenset({"needs_configuration", "unavailable", STATE_PARTIAL})


def changed_layers(report: dict) -> set[str]:
    return {
        layer for layer, entry in (report.get("layers") or {}).items()
        if isinstance(entry, dict) and (entry.get("extracted") or entry.get("retired"))
    }


async def previous_linkage(db: AsyncSession, project_id: str, build_id: str) -> dict[str, Any]:
    report = (await db.execute(
        select(KnowledgeStructuredBuild.report)
        .where(
            KnowledgeStructuredBuild.project_id == project_id,
            KnowledgeStructuredBuild.id != build_id,
            KnowledgeStructuredBuild.state == "completed",
        )
        .order_by(KnowledgeStructuredBuild.finished_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    linkage = (report or {}).get("linkage") if isinstance(report, dict) else None
    return linkage if isinstance(linkage, dict) else {}


async def run_linkage(
    context: BuildContext,
    *,
    build: KnowledgeStructuredBuild,
    report: dict,
    specs: dict[str, LayerSpec],
    deadline: float,
) -> bool:
    linkage = report.setdefault("linkage", {})
    requested = set(build.layers)
    changed = changed_layers(report)
    previous: dict[str, Any] | None = None
    for layer in LAYERS:
        spec = specs.get(layer)
        if spec is None or spec.link is None:
            continue
        if layer not in requested and not LINK_DEPENDS.get(layer, set()) & requested:
            continue
        progress = linkage.get(layer)
        resuming = isinstance(progress, dict) and progress.get("state") == STATE_PARTIAL
        if progress is not None and not resuming:
            continue  # finished in an earlier slice of this build
        if not resuming and not ({layer} | LINK_DEPENDS.get(layer, set())) & changed:
            if previous is None:
                previous = await previous_linkage(context.db, build.project_id, build.id)
            prior = previous.get(layer)
            if isinstance(prior, dict) and prior.get("state") and prior["state"] not in _UNSETTLED:
                linkage[layer] = {"state": STATE_UNCHANGED}
                continue
        if time.monotonic() > deadline:
            return False
        linkage[layer] = await spec.link(context, deadline=deadline, progress=progress if resuming else None)
        await context.db.commit()
        if linkage[layer].get("state") == STATE_PARTIAL:
            return False
    return True


__all__ = ["LINK_DEPENDS", "STATE_PARTIAL", "STATE_UNCHANGED", "changed_layers", "previous_linkage", "run_linkage"]
