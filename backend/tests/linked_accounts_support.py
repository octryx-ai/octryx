"""Shared helpers for the test_linked_accounts_* modules."""

from __future__ import annotations

from app.models import BuiltInToolConfig, WorkflowRun
from app.services.admin.project.named_connection_service import save_named
from app.services.workflow_runs.platform import bitbucket_cloud, scm
from app.services.workflow_runs.platform.dispatch import read_outcome
from app.services.workflow_runs.states import WAITING_WATCH

ACCOUNT = "557058:00000000-0000-0000-0000-00000000000b"


async def _cloud_run(db, admin) -> WorkflowRun:
    from tests.knowledge_evidence_seed_support import seed_workspace

    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=workspace_id, actor_id=None, payload={
        "name": "Bitbucket-Cloud", "bound_scopes": ["acme/payments"], "bitbucket_deployment": "cloud",
        "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "bot@example.test", "bitbucket_token": "t"})
    run = WorkflowRun(project_id=workspace_id, requested_by=admin.id, ticket_key="PAY-1", title="Totals",
                      repository="bitbucket:acme/payments", branch="feature/PAY-1-totals", context={},
                      workflow_kind="phased", workflow_key="k", status="waiting", waiting_kind=WAITING_WATCH)
    db.add(run)
    await db.flush()
    return run


def _scripted(monkeypatch, pr_answer: dict) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    async def dispatch(db_, run_, tool, arguments, *, capability_class):
        calls.append((tool, dict(arguments)))
        if tool == "search_jira_users":
            return read_outcome({"users": []})  # the platform email is no Atlassian account
        return read_outcome(pr_answer if tool == "create_bitbucket_pull_request" else {"status": "ok"})

    monkeypatch.setattr(scm, "dispatch_tool", dispatch)
    monkeypatch.setattr(bitbucket_cloud, "dispatch_tool", dispatch)
    return calls
