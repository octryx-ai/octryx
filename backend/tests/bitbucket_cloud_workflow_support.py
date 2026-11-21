"""Shared helpers for the test_bitbucket_cloud_workflow_* modules."""

from __future__ import annotations

from app.models import BuiltInToolConfig, WorkflowRun
from app.services.admin.project.named_connection_service import save_named
from tests.knowledge_evidence_seed_support import seed_workspace

EMAIL, TOKEN = "dev@example.test", "fake-cloud-token"


HEAD = "b" * 40


async def _cloud_workspace(db, *, bound: str = "acme/payments") -> str:
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=workspace_id, actor_id=None, payload={
        "name": "Bitbucket-Cloud", "bound_scopes": [bound], "bitbucket_deployment": "cloud",
        "bitbucket_url": "https://bitbucket.org", "bitbucket_username": EMAIL, "bitbucket_token": TOKEN})
    return workspace_id


def _run(workspace_id: str, requested_by: str, **extra) -> WorkflowRun:
    return WorkflowRun(project_id=workspace_id, requested_by=requested_by, ticket_key="PAY-1", title="Totals",
                       repository="bitbucket:acme/payments", branch="feature/PAY-1-totals", context={}, **extra)
