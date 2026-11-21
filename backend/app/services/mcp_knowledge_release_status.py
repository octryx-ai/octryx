"""``jira_release_status`` on the Knowledge MCP: the chat's live release status, with the chat's Jira gate.

In the chat, ``jira_release_status`` is a ``jira`` connector tool: it is visible and executable only
where the Workspace activates Jira (``tools/visibility.connector_activation_decision``). An MCP call has
no turn configuration, so the gate is re-applied here on the Workspace row itself:

- an **explicit deactivation** of Jira on the Workspace (``disabled_connectors``, ``jira_enabled:
  false``, ...) is ``denied`` with reason ``connector_not_active``, before any Jira call;
- otherwise the tool runs, and the service requires the Workspace's own Jira connection and the
  connector's explicit product mapping, so a Workspace without Jira configured is
  ``needs_configuration`` (activation by configuration, as in the chat).

The tool stays read-only: the service reads Jira through ``http.SourceReader``, which only sends
``GET`` and never follows redirects.
"""

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
