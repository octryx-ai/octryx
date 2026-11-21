"""A run of a platform-native Work item never touches Jira."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.secure_work.platform_items import create_platform_work_item
from app.services.workflow_runs.platform import jira
from app.services.workflow_runs.platform.dispatch import SUCCEEDED
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user

pytestmark = pytest.mark.asyncio


async def test_jira_steps_skip_and_the_platform_key_names_the_run(db, monkeypatch):
    admin = await admin_user(db)
    workspace = await seed_workspace(db)

    async def member(*_a, **_k):
        return workspace

    monkeypatch.setattr("app.services.secure_work.platform_items._require_project_access", member)
    item = await create_platform_work_item(db, current_user=admin, project_id=workspace, title="Packmate matching")
    run = SimpleNamespace(work_item_id=item.id, ticket_key=None, requested_by=admin.id, title="t", context={})

    async def never(*_a, **_k):
        raise AssertionError("Jira must not be called for a platform Work item")

    monkeypatch.setattr(jira, "dispatch_tool", never)
    created = await jira.create_issue(db, run, {"issue_type": "Story"})
    assert created.state == SUCCEEDED and created.result["status"] == "skipped"
    assert run.ticket_key == item.source_key
    assert (await jira.comment(db, run, {})).result["status"] == "skipped"
    assert (await jira.transition(db, run, {"work_state": "review"})).result["status"] == "skipped"
