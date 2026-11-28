"""Where a plugin's skills reach: only the Workspaces where the plugin is installed and active."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.plugin_install import SCOPE_PLATFORM, STATUS_ACTIVE, PluginInstall


async def skill_reach(db: AsyncSession) -> dict[str, set[str] | None]:
    reach: dict[str, set[str] | None] = {}
    rows = (await db.execute(select(PluginInstall.scope, PluginInstall.workspace_id, PluginInstall.status,
                                    PluginInstall.contributions_json, PluginInstall.source_json))).all()
    for scope, workspace_id, status, contributions, source in rows:
        image_part = scope == SCOPE_PLATFORM and (source or {}).get("kind") == "image"
        for item in contributions or []:
            if item.get("kind") != "skill":
                continue
            current = reach.setdefault(item["id"], set())
            if status != STATUS_ACTIVE or current is None or image_part:
                continue
            if scope == SCOPE_PLATFORM:
                reach[item["id"]] = None
            elif workspace_id:
                current.add(workspace_id)
    return reach


def outside_reach(reach: dict[str, set[str] | None], skill_id: str, project_id: str | None) -> bool:
    if skill_id not in reach:
        return False
    allowed = reach[skill_id]
    return allowed is not None and (project_id is None or project_id not in allowed)


__all__ = ["outside_reach", "skill_reach"]
