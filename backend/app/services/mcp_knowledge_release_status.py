"""``jira_release_status`` on the Knowledge MCP: the chat's live release status, with the chat's Jira gate. The gate is
re-applied on the Workspace row: an MCP call has no turn configuration."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..models import Project
from ..tools.context import ToolContext
from ..tools.jira_release_status import JiraReleaseStatusTool
from ..tools.knowledge_evidence._scope import authorized_workspace
from ..tools.visibility import connector_activation_decision

CONNECTOR = "jira"
NOT_ACTIVE = {
    "state": "denied",
    "reason": "connector_not_active",
    "error": "Jira is deactivated for this Workspace, so its release status cannot be queried.",
}


class McpJiraReleaseStatusTool:
    name = "jira_release_status"

    def __init__(self) -> None:
        self._tool = JiraReleaseStatusTool()

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        config = (
            await context.db.execute(select(Project.config).where(Project.id == authorized.project_id))
        ).scalar_one_or_none()
        active, reason, _ = connector_activation_decision(CONNECTOR, config if isinstance(config, dict) else {})
        if not active and reason == "explicit_connector_deactivation":
            return dict(NOT_ACTIVE)
        return await self._tool.execute(params, context)


__all__ = ["McpJiraReleaseStatusTool"]
