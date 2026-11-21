"""Blocking too much makes agents fail on harmless work: unknown tools, the shell of a changing phase, path rules
and the browser's public pages are allowed by default and logged in the run; each is an admin's switch back to
blocking (``device_runs.tool_defaults``) with a one-click remedy. Hard rules stay."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.devices.device_models import nearest_model
from app.services.devices.device_runs_keys import DeviceRunsPolicyError, normalize_device_runs, tool_defaults
from app.services.workflow_runs.states import STATUS_PAUSED
from tests.workflow_run_octryx_support import (
    ROOT,
    STRICT,
    _bound_run,
    _decide,
    _fix_definition,
    _hook,
    set_tool_defaults,
)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


async def _events(db, run_id: str) -> list[dict]:
    rows = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run_id, WorkflowRunEvent.kind == "tool_allowed_by_default"))).scalars().all()
    return [dict(row.detail) for row in rows]


@pytest.mark.asyncio
async def test_an_unknown_tool_runs_logged_and_a_strict_workspace_refuses_it_with_its_one_click_fix(db):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    spawn = await _decide(db, gateway, key, workspace_id, _hook("spawn_agent", message="build the API"))
    assert (spawn["decision"], spawn["reason"], spawn["rule_id"]) == (
        "allow", "allowed_by_default", "tool_defaults.unknown_tools")
    assert [(item["tool"], item["setting"]) for item in await _events(db, run.id)] == [
        ("spawn_agent", "tool_defaults.unknown_tools")]

    await set_tool_defaults(db, workspace_id, unknown_tools="deny")
    refused = await _decide(db, gateway, key, workspace_id, _hook("spawn_agent", message="x"))
    assert (refused["decision"], refused["reason"]) == ("deny", "tool_not_classified")
    assert refused["remedy"] == {"setting": "device_runs.tool_defaults.allowed_tools", "value": ["spawn_agent"],
                                 "tool": "spawn_agent"}
    await set_tool_defaults(db, workspace_id, unknown_tools="deny", allowed_tools=["spawn_agent"])
    assert (await _decide(db, gateway, key, workspace_id, _hook("spawn_agent", message="x")))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_waiting_run_refuses_only_changes_not_unknown_tools(db):
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    run.status = STATUS_PAUSED
    await db.flush()
    assert (await _decide(db, gateway, key, workspace_id, _hook("mcp__other__lookup", q="x")))["decision"] == "allow"
    edit = await _decide(db, gateway, key, workspace_id, _hook("Edit", file_path=f"{ROOT}/a.py", old_string="a",
                                                               new_string="b"))
    assert (edit["decision"], edit["reason"]) == ("deny", "run_paused")


@pytest.mark.asyncio
async def test_a_folder_goes_with_a_tracked_only_git_rm_and_plain_rm_r_is_pointed_there(db):
    """Git can undo changes to tracked files only, so untracked ones stay out."""
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))

    async def bash(command):
        return await _decide(db, gateway, key, workspace_id, _hook("Bash", command=command))

    assert (await bash("git rm -r -q old_module"))["reason"] == "allowed_by_default"
    for command in ("rm -rf old_module", "git rm -rf old_module"):
        refused = await bash(command)
        assert refused["decision"] == "deny" and "git rm -r old_module" in refused["message"], command
    assert (await bash("rm -rf ../other"))["decision"] == "deny"  # outside the folder: a hard rule
    assert (await bash("rm -rf build"))["decision"] == "allow"  # generated


@pytest.mark.asyncio
async def test_an_edit_outside_the_phases_paths_is_logged_and_protected_tests_stay_refused(db):
    definition = copy.deepcopy(_fix_definition())
    fix = next(node for node in definition["nodes"] if node["id"] == "fix")
    fix["config"]["workflow_contract"]["path_rules"] = {"protect_confirmed_tests": True, "write": ["pay/**"]}
    run, gateway, key, workspace_id = await _bound_run(db, definition)
    run.context = {**run.context, "confirmed_test_files": {"tests/test_totals.py::t": {
        "file": "tests/test_totals.py", "path": None, "sha256": None, "device": True}}}
    await db.flush()

    async def edit(path):
        hook = {**_hook("Edit", file_path=f"{ROOT}/{path}", old_string="a", new_string="b"),
                "workflow_run_facts": {"target_exists": True}}
        return await _decide(db, gateway, key, workspace_id, hook)

    assert (await edit("docs/notes.md"))["reason"] == "allowed_by_default"
    assert (await edit("tests/test_totals.py"))["reason"] == "confirmed_test_protected"
    await set_tool_defaults(db, workspace_id, **STRICT)
    strict = await edit("docs/notes.md")
    assert strict["reason"] == "phase_path_rule" and strict["remedy"]["value"] == "log"


@pytest.mark.asyncio
async def test_the_admin_applies_a_remedy_and_only_known_settings(client, db):
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
    from tests.policy_engine_support import bearer

    workspace_id = await seed_workspace(db)
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    viewer = await seed_member(db, workspace_id=workspace_id, role="viewer")
    await db.commit()
    auth_headers = bearer(owner)
    path = f"/api/v1/workspaces/{workspace_id}/agent-gateway/device-runs/remedy"
    assert (await client.post(path, headers=bearer(viewer), json={
        "setting": "device_runs.tool_defaults.shell", "value": "free"})).status_code == 403
    answer = await client.post(path, headers=auth_headers, json={
        "setting": "device_runs.tool_defaults.allowed_tools", "value": ["spawn_agent"], "tool": "spawn_agent"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["tool_defaults_effective"]["allowed_tools"] == ["spawn_agent"]
    answer = await client.post(path, headers=auth_headers, json={"setting": "device_runs.tool_defaults.shell",
                                                                 "value": "free"})
    assert answer.json()["tool_defaults_effective"]["shell"] == "free" and "shell" not in answer.json()[
        "tool_defaults"]  # the default is not stored
    for bad in ({"setting": "device_runs.tool_defaults.shell", "value": "root"},
                {"setting": "device_runs.enabled", "value": True}):
        assert (await client.post(path, headers=auth_headers, json=bad)).status_code == 400


def test_the_settings_default_to_allow_and_reject_unknown_values():
    assert tool_defaults({}) == {"unknown_tools": "allow", "web_tools": "all", "shell": "free", "path_rules": "log",
                                 "device_models": "nearest", "network": "open", "browser": "read_external",
                                 "allowed_tools": []}
    assert normalize_device_runs({"tool_defaults": {"shell": "strict"}}, "p") == {"tool_defaults": {"shell": "strict"}}
    for bad in ({"shell": "root"}, {"other": "x"}, {"allowed_tools": "spawn_agent"}):
        with pytest.raises(DeviceRunsPolicyError):
            normalize_device_runs({"tool_defaults": bad}, "p")


def test_a_model_outside_the_list_becomes_the_nearest_listed_one():
    options = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    assert nearest_model("claude-sonnet-5", options) == "claude-sonnet-5-5"
    assert nearest_model("gpt-6-luna", ["gpt-6.1-sol", "gpt-6-luna-mini"]) == "gpt-6-luna-mini"
    assert nearest_model("x", []) == ""


@pytest.mark.asyncio
async def test_refusals_and_outside_path_edits_reach_the_run_and_the_reviewer(db):
    """A refusal and its one-click fix are a run event; an edit outside the phase's paths is a note for the reviewer,
    never a blocker."""
    from app.services.workflow_runs.review.evidence import outside_phase_paths

    definition = copy.deepcopy(_fix_definition(protect=False))
    next(node for node in definition["nodes"] if node["id"] == "fix")["config"]["workflow_contract"]["path_rules"] = {
        "write": ["tests/**"]}
    run, gateway, key, workspace_id = await _bound_run(db, definition)
    hook = {**_hook("Write", file_path=f"{ROOT}/pay/totals.py", content="x"), "workflow_run_facts": {}}
    assert (await _decide(db, gateway, key, workspace_id, hook))["reason"] == "allowed_by_default"
    note = await outside_phase_paths(db, run)
    assert "phase fix: /work/repo/pay/totals.py" in note and "not as a blocking finding" in note

    await set_tool_defaults(db, workspace_id, unknown_tools="deny")
    await _decide(db, gateway, key, workspace_id, _hook("spawn_agent", message="x"))
    [denied] = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "tool_denied"))).scalars().all()
    assert (denied.detail["tool"], denied.detail["reason"]) == ("spawn_agent", "tool_not_classified")
    assert denied.detail["remedy"]["setting"] == "device_runs.tool_defaults.allowed_tools"


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_tool_step_and_the_turns_answer(db):
    """The chat shows a refusal's fix at the tool step (``tool_result.remedy``) and lists the
    refusal with the turn's answer (its ``message_id``)."""
    from types import SimpleNamespace

    from app.models import Message, ToolCall
    from app.services.devices.job_events import _bind_refusals
    from app.services.devices.jobs_channel import _with_remedy

    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    await set_tool_defaults(db, workspace_id, unknown_tools="deny")
    await _decide(db, gateway, key, workspace_id, {**_hook("spawn_agent", message="x"), "tool_use_id": "tu-1"})
    result = await _with_remedy(db, {"kind": "tool_result", "tool_use_id": "tu-1", "is_error": True})
    assert result["remedy"]["tool"] == "spawn_agent"
    assert "remedy" not in await _with_remedy(db, {"kind": "tool_result", "tool_use_id": "tu-2", "is_error": True})

    answer = Message(session_id=gateway.id, role="assistant", content="done")
    db.add(answer)
    job = SimpleNamespace(claude_session_id=key, owner_user_id=gateway.user_id)
    await _bind_refusals(db, job, answer)
    [row] = (await db.execute(select(ToolCall).where(ToolCall.session_id == gateway.id))).scalars().all()
    assert row.message_id == answer.id


@pytest.mark.asyncio
async def test_tool_defaults_writes_merge_key_by_key_and_none_resets(db):
    from app.models import Project
    from app.services.devices.workspace_policy import set_workspace_device_runs, workspace_device_runs
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

    workspace_id = await seed_workspace(db)
    actor = await seed_member(db, workspace_id=workspace_id, role="owner")
    project = await db.get(Project, workspace_id)
    await set_workspace_device_runs(db, project=project, patch={"tool_defaults": {"shell": "strict"}}, actor_id=actor)
    await set_workspace_device_runs(db, project=project, patch={"tool_defaults": {"browser": "loopback"}},
                                    actor_id=actor)
    stored = (await workspace_device_runs(db, workspace_id))["tool_defaults"]
    assert stored == {"shell": "strict", "browser": "loopback"}
    await set_workspace_device_runs(db, project=project, patch={"tool_defaults": {"shell": None}}, actor_id=actor)
    assert (await workspace_device_runs(db, workspace_id))["tool_defaults"] == {"browser": "loopback"}
    # The default's own value is no stored choice: a later change of the default reaches the Workspace.
    await set_workspace_device_runs(db, project=project, patch={"tool_defaults": {"browser": "read_external"}},
                                    actor_id=actor)
    assert (await workspace_device_runs(db, workspace_id))["tool_defaults"] == {}


def test_the_seat_settings_say_whether_a_switch_was_set():
    from types import SimpleNamespace

    from app.api.routes.data_classification import _seat_values

    unset = _seat_values(SimpleNamespace(config={}), [])
    assert (unset["seat_mode_set"], unset["codex_seat_mode_set"]) == (False, False)
    stored = _seat_values(SimpleNamespace(config={"agent_gateway_policy": {"seat_mode": "forbidden"}}), [])
    assert (stored["seat_mode"], stored["seat_mode_set"], stored["codex_seat_mode_set"]) == ("forbidden", True, False)
