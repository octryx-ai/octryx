"""Sub-agent work packages of a workflow phase."""

from __future__ import annotations

import pytest

from app.models import ToolCall
from app.services.agent_gateway.tool_execution import record_tool_execution
from app.time_utils import utc_now
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")






class Launcher:
    def __init__(self):
        self.calls = []

    async def __call__(self, db, **kwargs):
        self.calls.append(kwargs)
















@pytest.mark.asyncio
async def test_octryx_subagent_stop_reports_per_child_and_never_advances(db):
    from tests.workflow_run_octryx_support import _bound_run, _call

    run, gateway, _key, _workspace = await _bound_run(db)
    hook = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_child_1",
            "agent_id": "agent-7"}
    await record_tool_execution(db, session=gateway, hook_input=hook)
    row = (await db.execute(ToolCall.__table__.select().where(ToolCall.request_id == "toolu_child_1"))).first()
    assert row.parameters["agent_id"] == "agent-7"

    from app.services.workflow_runs.octryx.stop import run_stop

    at = utc_now()
    rows = [_call(gateway, "Bash", at=at, command="pytest -q", excerpt="", agent_id="agent-7")]
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "SubagentStop", "agent_id": "agent-7"},
                            tool_calls=rows, test_prefixes=(("pytest",),))
    assert answer["state"] == "passed" and run.current_node_id == "fix"
    assert run.context["octryx_children"]["agent-7"]["tool_calls"] == 1


