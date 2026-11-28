"""Only a platform catalog action counts as allowed by its published workflow; a free ``tool`` step still
needs the project's explicit allow for a high-risk tool."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.workflow_runs import platform_actions
from app.services.workflow_runs.graph import PhasedNode
from app.services.workflow_runs.platform import dispatch


class _Db:
    def add(self, _row) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", [True, False])
async def test_the_tool_context_marks_only_typed_actions(monkeypatch, typed):
    async def no_session(_db, _run):
        return None

    async def no_config(_project_id, _db):
        return {}

    monkeypatch.setattr(dispatch, "main_session_id", no_session)
    monkeypatch.setattr(dispatch, "get_project_config", no_config)
    run = SimpleNamespace(requested_by="u1", project_id=None)
    context = await dispatch.tool_context(_Db(), run, "read_only", workspace_root="/tmp/w", typed_action=typed)
    assert context.workflow_platform_action is typed


@pytest.mark.asyncio
async def test_a_free_tool_step_is_dispatched_as_not_typed(monkeypatch):
    seen: dict = {}

    async def fake_dispatch(db, run, tool, arguments, *, capability_class, typed_action=True, **_):
        seen.update(tool=tool, typed_action=typed_action)
        return dispatch.ToolOutcome(dispatch.SUCCEEDED, {}, "")

    monkeypatch.setattr(platform_actions, "dispatch_tool", fake_dispatch)
    monkeypatch.setattr(platform_actions, "record_event", lambda *a, **k: None)
    run = SimpleNamespace(id="r1", context={}, node_state={"entry": 1}, current_node_id="act", requested_by="u1",
                          project_id=None, created_at=None, ticket_key=None, repository=None, branch=None,
                          workflow_key="w")
    node = PhasedNode("act", "platform_action", "Comment", {"tool": "add_jira_comment", "arguments": {"body": "q"}})
    await platform_actions.run_platform_action(_Db(), run, node)
    assert seen == {"tool": "add_jira_comment", "typed_action": False}
