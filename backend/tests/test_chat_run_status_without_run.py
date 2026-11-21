"""A chat that follows no workflow run says so plainly, with the Workspace's recent runs.

Asked "What's the status of my current workflow run?" by a member of more than one Workspace, in a chat that sits
in one of them where no run was started, ``workflow_run_status`` must not answer "No Workspace is set for this MCP
connection" (``needs_configuration``), which makes a model tell the person to reconfigure OAuth instead of
answering "no run in this chat".
"""

from __future__ import annotations

import pytest

from app.tools.context import ToolContext

CHAT_STATE = {"class": "read_only", "enforced": True, "source": "chat_default", "escalation_decision": None,
              "chat_connector_writes": True}


def _chat_context(user_id: str, chat_id: str, workspace_id: str, *, all_workspaces: list[str], db) -> ToolContext:
    # As ``prepare_agent_run`` builds it: every Workspace of the person, the chat's own in ``project_config``.
    return ToolContext(user_id=user_id, project_ids=all_workspaces, roles=["admin"], session_id=chat_id,
                       project_config={"project_id": workspace_id}, db=db, agent_mode_key="diagnosis",
                       capability_type="diagnosis", run_capability=dict(CHAT_STATE))


@pytest.mark.asyncio
async def test_t16_a_chat_without_a_run_in_a_multi_workspace_account_says_no_run_not_configuration(db):
    from app.services.workflow_runs.records import new_chat_session
    from app.tools.registry import execute_tool
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import admin_user

    demo_shop, other = await seed_workspace(db), await seed_workspace(db)
    admin = await admin_user(db)
    chat = await new_chat_session(db, admin, demo_shop)
    context = _chat_context(admin.id, chat.id, demo_shop, all_workspaces=[other, demo_shop], db=db)

    status = await execute_tool("workflow_run_status", {}, context)

    assert status["state"] == "ok" and status["reason"] == "no_run_bound"
    assert status["workflow_run"] is None and status["recent_runs"] == []
    assert "No workflow run is running in this chat" in status["message"]
    assert "needs_configuration" not in str(status) and "octryx" not in status["message"]


@pytest.mark.asyncio
async def test_t17_the_latest_run_of_the_workspace_is_named_so_the_chat_can_summarise_it(db):
    from app.services.workflow_runs.records import new_chat_session, start_run
    from app.tools.registry import execute_tool
    from tests.knowledge_evidence_seed_support import seed_workspace
    from tests.phased_workflow_fixtures import admin_user, publish_phased
    from tests.test_workflow_run_octryx_decisions import CONFIRM, _definition

    demo_shop, other = await seed_workspace(db), await seed_workspace(db)
    admin = await admin_user(db)
    key = await publish_phased(db, _definition(CONFIRM))
    run = await start_run(db, user=admin, workflow_key=key, project_id=demo_shop,
                          session=await new_chat_session(db, admin, demo_shop))
    chat = await new_chat_session(db, admin, demo_shop)
    context = _chat_context(admin.id, chat.id, demo_shop, all_workspaces=[demo_shop, other], db=db)

    status = await execute_tool("workflow_run_status", {}, context)

    assert status["state"] == "ok" and status["workflow_run"] is None
    [recent] = status["recent_runs"]
    assert (recent["run_id"], recent["workflow_key"], recent["status"]) == (run.id, key, run.status)
    # The listed run is readable by its id from this chat.
    read = await execute_tool("workflow_run_status", {"run_id": run.id}, context)
    assert read["state"] == "ok" and read["workflow_run"]["run"]["id"] == run.id
