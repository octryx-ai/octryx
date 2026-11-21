"""Which workflows use one agent - read-only, bounded.

Response contract::

    {"agent_id": str,
     "workflows":  [entry, ...],   # newest workflow first
     "truncated": bool}            # true when the bound cut the list

    entry = {"kind": "workflow", "id": str, "name": str,
             "workspace_id": str | None,     # None = Global
             "workspace_name": str | None,   # only when the caller may read that Workspace
             "reference_state": "published" | "current_draft" | "older_revision_only",
             "revision": int,                # the referencing workflow version
             "latest_revision": int,         # the version the editor link opens (always the latest)
             "latest_references_agent": bool}  # whether that latest version still references the agent

Every rule is an existing one: the agent itself follows the agent panel's owner
scope (another owner's or an unknown agent is the same 404); workflows follow the
workflow API (global admins read every workflow). Nothing the caller cannot read is
named or counted. No new persistence: stored versions are scanned, bounded.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentDefinition, Project, User
from ..admin.governance.admin_access_service import is_global_admin
from ..agent_visibility import visible_agent_clause
from ..workspace_authorization import authorize_workspace
from .flows import flow_references
from .states import Reference

AGENT_NOT_FOUND_DETAIL = "Agent not found"
#: Entries returned per kind; more marks the result truncated.
MAX_ITEMS_PER_KIND = 50


class _WorkspaceNames:
    """Workspace display names, only for Workspaces the caller may read (``workspace_authorization``)."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self._db = db
        self._user = user
        self._names: dict[str, str | None] = {}

    async def name(self, workspace_id: str | None) -> str | None:
        if not workspace_id:
            return None
        if workspace_id not in self._names:
            self._names[workspace_id] = await self._readable_name(workspace_id)
        return self._names[workspace_id]

    async def _readable_name(self, workspace_id: str) -> str | None:
        try:
            await authorize_workspace(
                self._db, current_user=self._user, workspace_id=workspace_id, require_author=False
            )
        except HTTPException:
            return None
        return (await self._db.execute(select(Project.name).where(Project.id == workspace_id))).scalar_one_or_none()


def _entry(
    kind: str, row_id: str, name: str, workspace_id: str | None, workspace_name: str | None, reference: Reference
) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": row_id,
        "name": name,
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "reference_state": reference.state,
        "revision": reference.revision,
        "latest_revision": reference.latest_revision,
        "latest_references_agent": reference.latest_references_agent,
    }


async def list_agent_references(db: AsyncSession, *, user: User, agent_id: str) -> dict[str, Any]:
    agent_key = str(agent_id or "").strip()
    agent = (
        await db.execute(
            select(AgentDefinition).where(AgentDefinition.id == agent_key, await visible_agent_clause(db, user.id))
        )
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=AGENT_NOT_FOUND_DETAIL)
    names = _WorkspaceNames(db, user)

    workflows: list[dict[str, Any]] = []
    flows_truncated = False
    if await is_global_admin(db, user.id):
        found, flows_truncated = await flow_references(db, agent_id=agent.id, limit=MAX_ITEMS_PER_KIND)
        for flow, reference in found:
            workspace = flow.project_id or None
            workflows.append(_entry("workflow", flow.id, flow.name, workspace, await names.name(workspace), reference))

    return {"agent_id": agent.id, "workflows": workflows, "truncated": bool(flows_truncated)}


__all__ = ["AGENT_NOT_FOUND_DETAIL", "MAX_ITEMS_PER_KIND", "list_agent_references"]
