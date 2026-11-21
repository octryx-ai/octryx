"""Shared helpers for the test_named_connection_service_lookups_* modules."""

from __future__ import annotations

import base64

from app.models import BuiltInToolConfig
from app.services.admin.project.named_connection_service import save_named
from tests.knowledge_evidence_seed_support import seed_workspace

ACCOUNT = "557058:00000000-0000-0000-0000-0000000000aa"


OCTRYX = "https://first-site.atlassian.net"


SECOND = "https://second.atlassian.net"


def _basic(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


async def _jira_workspace(db, *connections: tuple[str, str, list[str]]) -> str:
    """A Workspace whose Jira entry is active but has no target, served by named Jira Cloud connections."""
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    for name, url, keys in connections:
        await save_named(db, connector="jira", project_id=workspace_id, actor_id=None, payload={
            "name": name, "bound_scopes": keys, "jira_url": url, "jira_auth_mode": "cloud_api_token",
            "jira_email": f"bot@{name.lower()}.test", "jira_token": f"token-{name.lower()}"})
    return workspace_id
