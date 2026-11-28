"""``jira_release_status``: the live status of one release of a product, queried from Jira now."""

from __future__ import annotations

from typing import Any

from ..services.knowledge.sources.sync.jira_release_status import jira_release_status
from .context import ToolContext
from .jira_impl._jira_evidence import with_release_status_sources
from .knowledge_evidence._scope import authorized_workspace

STATE_MESSAGES = {
    "needs_configuration": (
        "Release status is not configured for this product: the Workspace needs a Jira connection and a Jira "
        "Source Sync connector whose release configuration maps a Jira project to this product."
    ),
    "not_found": "Jira has no version of this product with that version name.",
    "denied": "The Workspace's Jira connection may not read this project.",
    "unavailable": "Jira could not be queried right now.",
    "invalid_request": "The product or version was empty or not a version.",
}


class JiraReleaseStatusTool:
    name = "jira_release_status"
    description = (
        "Query Jira live for the status of one product release (released, release date, issue counts by status "
        "category, open blockers). Read-only."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        result = await jira_release_status(
            context.db,
            project_id=authorized.project_id,
            product=params.get("product"),
            version=params.get("version"),
        )
        if result["state"] != "ok":
            return {**result, "error": STATE_MESSAGES.get(str(result["state"]), STATE_MESSAGES["unavailable"])}
        # The release's version page and each open blocker's issue page are the citable sources.
        return {**with_release_status_sources(result), "source": "live Jira query"}


__all__ = ["JiraReleaseStatusTool"]
