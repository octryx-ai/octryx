"""A Workspace's named connection for tests (the sole runtime source of a connector).

A flat ``jira_url`` / ``confluence_url`` / ``bitbucket_url`` in the Workspace config makes no connector active, so a
test that wants a connector's tools offered gives the Workspace a connection.
"""

from __future__ import annotations

import uuid

from app.models import ConnectionWorkspace, ConnectorNamedConnection
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value

URL_AND_SECRET = {
    "jira": ("jira_url", "jira_token"),
    "confluence": ("confluence_url", "confluence_token"),
    "bitbucket": ("bitbucket_url", "bitbucket_token"),
}


async def connect(db, tool: str, workspace_id: str) -> str:
    """A token connection of ``tool`` available in ``workspace_id`` (agent tools level ``write``)."""
    url_field, secret_field = URL_AND_SECRET[tool]
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name=tool, project_id=None, scope_key="global", name=f"{tool}-{uuid.uuid4().hex[:6]}",
        bound_scopes=[], config={url_field: f"https://{tool}.example.test", f"{tool}_auth_mode": "bearer_pat"},
        available_in="selected", agent_tools_level="write", is_active=True,
    )
    db.add(row)
    await db.flush()
    db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    stored = await set_secret_value(db, tool_name=tool, field_name=named_secret_field(secret_field, row.id),
                                    project_id=None, value=f"fake-{tool}")
    row.config = {**row.config, f"{secret_field}_secret_ref": stored.id}
    await db.flush()
    return row.id
