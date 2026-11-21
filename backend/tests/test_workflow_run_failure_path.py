"""DevOps workflows S8: the failure path — a comment per failed round, one follow-up issue, the failure card."""

from __future__ import annotations

import pytest

from app.models.runtime.secure_work import WorkItemWorkflowDefinition
from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.views import run_view
from tests.phased_workflow_fixtures import admin_user, phased_definition
from tests.test_workflow_run_pause import _turn
from tests.test_workflow_run_platform_actions import FakeTools, _item, _run


def _with_policy(max_iterations: int = 1) -> dict:
    definition = phased_definition(max_iterations=max_iterations)
    definition["failure_policy"] = {"comment_per_round": True, "follow_up_on_loop_limit": True,
                                    "follow_up_issue_type": "Bug"}
    definition["nodes"].append({"id": "stopped", "type": "outcome", "config": {"outcome": "blocked"}})
    return definition


@pytest.mark.asyncio
async def test_each_failed_round_comments_and_the_loop_limit_files_one_follow_up(db, monkeypatch):
    tools = FakeTools(monkeypatch, {"create_jira_ticket": [{"ticket_id": "PAY-900", "status": "created"}]})
    item = await _item(db)
    run = await _run(db, _with_policy(), work_item_id=item.id)
    session_id = await _session(db, run)
    await _turn(db, session_id, ["knowledge_search"])  # round 1 fails → comment, loop back
    assert [call[0] for call in tools.calls] == ["add_jira_comment"]
    assert "A source was read" in tools.calls[0][1]["body"]
    await _turn(db, session_id, ["knowledge_search"])  # round 2 at the limit → paused + one follow-up issue
    assert (run.status, run.pause_reason, run.context["follow_up_issue"]) == ("paused", "loop_limit", "PAY-900")
    assert [call[0] for call in tools.calls][1:] == ["create_jira_ticket", "add_jira_comment"]
    assert tools.calls[1][1]["summary"].startswith(f"Follow-up of {item.source_key}")

    admin = await admin_user(db)
    view = await run_view(db, run, access="write", user=admin)
    assert view["failure"]["follow_up_issue"] == "PAY-900" and "A source was read" in view["failure"]["findings"]
    labels = {action["key"]: action["label"] for action in view["actions"]}
    assert labels["continue"] == "Retry" and labels["change_plan"] == "Re-clarify" and "follow_up" not in labels
    await perform_action(db, run, user=admin, body={"action": "follow_up"})  # already filed: still one issue
    assert [call[0] for call in tools.calls].count("create_jira_ticket") == 1


async def _session(db, run):
    from app.services.workflow_runs.records import main_session_id

    return await main_session_id(db, run)


@pytest.mark.asyncio
async def test_out_of_scope_findings_get_a_follow_up_and_a_blocked_outcome_blocks_the_work_item(db, monkeypatch):
    tools = FakeTools(monkeypatch, {"create_jira_ticket": [{"ticket_id": "PAY-901", "status": "created"}]})
    admin = await admin_user(db)
    db.add(WorkItemWorkflowDefinition(name="wb", states_json=[], mappings_json={"blocked": {"sync_back": False}},
                                      is_default=True, is_active=True, created_by=admin.id, updated_by=admin.id))
    item = await _item(db)
    definition = _with_policy()
    definition["failure_policy"]["follow_up_on_loop_limit"] = False
    run = await _run(db, definition, work_item_id=item.id)
    session_id = await _session(db, run)
    for _ in range(2):
        await _turn(db, session_id, ["knowledge_search"])
    assert run.status == "paused" and "follow_up_issue" not in run.context
    assert "follow_up" in {action["key"] for action in await available_actions(db, run, access="write", user=admin)}
    await perform_action(db, run, user=admin, body={"action": "follow_up"})
    assert run.context["follow_up_issue"] == "PAY-901"
    await perform_action(db, run, user=admin, body={"action": "abort", "reason": "Out of scope for now"})
    assert (run.outcome, item.work_state) == ("stopped", "blocked")
    assert "create_jira_ticket" in tools.tools()

    blocked = await _run(db, {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "e", "source_node_id": "start", "target_node_id": "end"}],
    }, work_item_id=(await _item(db)).id)
    assert blocked.outcome == "blocked"
