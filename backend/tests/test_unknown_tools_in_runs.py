from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.workflow_runs.states import STATUS_PAUSED, STATUS_WAITING
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import (
    ROOT,
    _bound_run,
    _decide,
    _fix_definition,
    _hook,
    _launcher,
    set_tool_defaults,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")

UNKNOWN = _hook("mcp__other__lookup", q="x")
SETTINGS = [("allow", "allow"), ("deny", "deny")]


def _read_only_definition() -> dict:
    return _fix_definition(capability="read_only", tools=["read_workspace_file"])


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["allow", "deny"])
async def test_a_read_only_phase_refuses_an_unknown_tool_even_when_listed(db, setting):
    _run, gateway, key, workspace_id = await _bound_run(db, _read_only_definition())
    await set_tool_defaults(db, workspace_id, unknown_tools=setting, allowed_tools=["mcp__other__lookup"])
    refused = await _decide(db, gateway, key, workspace_id, UNKNOWN)
    assert (refused["decision"], refused["reason"]) == ("deny", "tool_not_classified")
    assert not refused.get("remedy")
    assert "plan mode" not in refused["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "expected"), SETTINGS)
async def test_a_working_phase_follows_the_unknown_tools_setting(db, setting, expected):
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    await set_tool_defaults(db, workspace_id, unknown_tools=setting)
    decided = await _decide(db, gateway, key, workspace_id, UNKNOWN)
    assert decided["decision"] == expected
    if expected == "deny":
        assert decided["reason"] == "tool_not_classified"
        assert decided["remedy"]["value"] == ["mcp__other__lookup"]
        assert "plan mode" not in decided["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "expected"), SETTINGS)
async def test_a_paused_run_follows_the_unknown_tools_setting_and_still_refuses_changes(db, setting, expected):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status = STATUS_PAUSED
    await set_tool_defaults(db, workspace_id, unknown_tools=setting)
    decided = await _decide(db, gateway, key, workspace_id, UNKNOWN)
    assert decided["decision"] == expected
    if expected == "deny":
        assert decided["reason"] == "tool_not_classified"
        assert decided["remedy"]["value"] == ["mcp__other__lookup"]
        assert "plan mode" not in decided["message"]
    else:
        assert decided["reason"] == "allowed_by_default"
    edit = await _decide(db, gateway, key, workspace_id, _hook("Edit", file_path=f"{ROOT}/a.py", old_string="a",
                                                               new_string="b"))
    assert (edit["decision"], edit["reason"]) == ("deny", "run_paused")


@pytest.mark.asyncio
async def test_a_paused_read_only_phase_refuses_an_unknown_tool_even_when_listed(db):
    run, gateway, key, workspace_id = await _bound_run(db, _read_only_definition())
    run.status = STATUS_PAUSED
    await set_tool_defaults(db, workspace_id, unknown_tools="allow", allowed_tools=["mcp__other__lookup"])
    refused = await _decide(db, gateway, key, workspace_id, UNKNOWN)
    assert (refused["decision"], refused["reason"]) == ("deny", "tool_not_classified")


@pytest.mark.asyncio
@pytest.mark.parametrize("paused", [False, True])
async def test_allowed_tools_lets_the_listed_tool_through_under_deny(db, paused):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    if paused:
        run.status = STATUS_PAUSED
    await set_tool_defaults(db, workspace_id, unknown_tools="deny", allowed_tools=["mcp__other__lookup"])
    assert (await _decide(db, gateway, key, workspace_id, UNKNOWN))["decision"] == "allow"
    other = await _decide(db, gateway, key, workspace_id, _hook("mcp__other__write", q="x"))
    assert (other["decision"], other["reason"]) == ("deny", "tool_not_classified")


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["allow", "deny"])
async def test_a_read_only_session_outside_a_run_refuses_an_unknown_tool_even_when_listed(db, setting):
    _run, _gateway, _key, workspace_id = await _bound_run(db)
    await set_tool_defaults(db, workspace_id, unknown_tools=setting, allowed_tools=["mcp__other__lookup"])
    gateway, key = await _launcher(db, await admin_user(db), workspace_id)
    refused = await _decide(db, gateway, key, workspace_id, {**UNKNOWN, "permission_mode": "plan"})
    assert (refused["decision"], refused["reason"]) == ("deny", "tool_not_classified")
    assert not refused.get("remedy")


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "expected"), SETTINGS)
async def test_a_run_waiting_at_a_gate_follows_the_unknown_tools_setting(db, setting, expected):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status, run.current_node_id = STATUS_WAITING, "green"
    await set_tool_defaults(db, workspace_id, unknown_tools=setting, allowed_tools=["mcp__other__listed"])
    decided = await _decide(db, gateway, key, workspace_id, UNKNOWN)
    assert decided["workflow_run"]["phase"] is None
    assert decided["decision"] == expected
    if expected == "deny":
        assert decided["reason"] == "tool_not_classified"
        assert decided["remedy"]["value"] == ["mcp__other__lookup"]
        assert "plan mode" not in decided["message"]
    listed = await _decide(db, gateway, key, workspace_id, _hook("mcp__other__listed", q="x"))
    assert (listed["decision"], listed["reason"]) == ("allow", "allowed_by_default")
    logged = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "tool_allowed_by_default"))).scalars().all()
    expected_logged = ["mcp__other__listed"] if expected == "deny" else ["mcp__other__lookup", "mcp__other__listed"]
    assert [row.detail["tool"] for row in logged] == expected_logged
    edit = await _decide(db, gateway, key, workspace_id, _hook("Edit", file_path=f"{ROOT}/a.py", old_string="a",
                                                               new_string="b"))
    assert (edit["decision"], edit["reason"]) == ("deny", "run_waiting")


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["WebSearch", "web.run"])
async def test_a_paused_run_keeps_the_web_tools_setting(db, tool):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status = STATUS_PAUSED
    await set_tool_defaults(db, workspace_id, web_tools="off")
    refused = await _decide(db, gateway, key, workspace_id, _hook(tool, query="x"))
    assert (refused["decision"], refused["reason"]) == ("deny", "outside_phase_tools")


@pytest.mark.asyncio
async def test_a_paused_run_keeps_the_browser_setting(db):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status = STATUS_PAUSED
    await set_tool_defaults(db, workspace_id, browser="loopback")
    navigate = "mcp__playwright__browser_navigate"
    refused = await _decide(db, gateway, key, workspace_id, _hook(navigate, url="https://example.com/"))
    assert refused["decision"] == "deny"
    local = await _decide(db, gateway, key, workspace_id, _hook(navigate, url="http://127.0.0.1:8765/"))
    assert local["decision"] == "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize(("setting", "expected"), SETTINGS)
async def test_a_run_waiting_at_a_gate_treats_web_search_by_the_unknown_tools_setting(db, setting, expected):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status, run.current_node_id = STATUS_WAITING, "green"
    await set_tool_defaults(db, workspace_id, unknown_tools=setting)
    decided = await _decide(db, gateway, key, workspace_id, _hook("WebSearch", query="x"))
    assert decided["workflow_run"]["phase"] is None
    assert decided["decision"] == expected
