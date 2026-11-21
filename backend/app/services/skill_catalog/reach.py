"""Which Workspaces receive a skill (detail → Workspaces and the catalog's Workspaces column).

Read-only, computed with the same effective-set function as delivery (``effective.candidates``) for every active
Workspace and surface: a Workspace is listed for a skill when the skill is assigned there on at least one surface;
per surface the row says whether it is delivered, how it is assigned (``all`` | ``skill`` | ``category:<key>``),
the readiness when delivered, and the reason when it is not.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project
from ...models.agent.skill_catalog import SKILL_KIND_MCP_SERVER
from .effective import candidates, workspace_policy
from .extension import SURFACE_PLATFORM_CHAT, SURFACES
from .readiness import readiness


async def skill_reach(db: AsyncSession, *, skill_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """``{skill_id: [{project_id, name, surfaces: {surface: {...}}}]}``; ``skill_id`` limits the answer to one."""
    projects = list((await db.execute(select(Project).where(Project.is_active.is_not(False))
                                      .order_by(Project.name))).scalars())
    reach: dict[str, list[dict[str, Any]]] = {}
    for project in projects:
        policy = await workspace_policy(db, project.id)
        rows: dict[str, dict[str, Any]] = {}
        for surface in SURFACES:
            for item in await candidates(db, project_id=project.id, surface=surface, policy=policy):
                if skill_id and item.skill.id != skill_id:
                    continue
                if not item.assigned_by or (item.skill.kind == SKILL_KIND_MCP_SERVER
                                            and surface == SURFACE_PLATFORM_CHAT):
                    continue
                row = rows.setdefault(item.skill.id, {"project_id": project.id, "name": project.name,
                                                      "surfaces": {}})
                row["surfaces"][surface] = {
                    "delivered": item.delivered, "assigned_by": item.assigned_by, "reason": item.reason,
                    "readiness": readiness(item, project, surface) if item.delivered else None}
        for found, row in rows.items():
            reach.setdefault(found, []).append(row)
    return reach


def delivered_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if any(entry["delivered"] for entry in row["surfaces"].values()))


__all__ = ["delivered_count", "skill_reach"]
