"""A connector a Workspace holds its own account for needs no global entry: it is listed for the
Workspace and gets its card under Automation → Connectors."""

from __future__ import annotations

from app.models import BuiltInToolConfig
from app.services.admin.project.admin_project_connector_access_service import list_project_connector_access
from app.services.admin.project.named_connection_service import save_named
from app.services.admin.project.named_connection_workspaces import with_workspace_connection_counts
from tests.knowledge_evidence_seed_support import seed_workspace


async def test_a_workspace_can_switch_on_source_control_and_its_named_connectors_without_a_global_entry(db):
    workspace_id = await seed_workspace(db)
    listed = {row["connector_name"]: row for row in (await list_project_connector_access(
        db, project_id=workspace_id))["connectors"]}
    assert {"bitbucket", "github", "gitlab", "confluence", "jira"} <= set(listed)
    assert listed["bitbucket"]["global_configured"] is False
    db.add(BuiltInToolConfig(tool_name="grafana", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="grafana", project_id=workspace_id, actor_id=None, payload={
        "name": "Grafana-prod", "bound_scopes": ["prod"], "grafana_url": "https://grafana.example.test",
        "grafana_token": "fake-token"})
    assert "grafana" in {row["connector_name"] for row in (await list_project_connector_access(
        db, project_id=workspace_id))["connectors"]}


async def test_automation_gets_each_connectors_count_of_workspace_connections(db):
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=workspace_id, actor_id=None, payload={
        "name": "Bitbucket-Cloud", "bound_scopes": ["acme/payments"], "bitbucket_deployment": "cloud",
        "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "dev@example.test",
        "bitbucket_token": "fake-token"})
    rows = await with_workspace_connection_counts(db, [{"tool_name": "bitbucket", "configured": False},
                                                       {"tool_name": "aws", "configured": True}])
    counts = {row["tool_name"]: row["workspace_connections"] for row in rows}
    assert counts["bitbucket"] >= 1 and "fake-token" not in str(rows)
