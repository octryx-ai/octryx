"""A phase's reaction to repeated refusals is workflow data: one mechanism for
"the phase cannot do this" — pause with a proposal, escalate the size class, or go back to a node."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.workflow_runs import refusals
from app.services.workflow_runs.states import PAUSE_PHASE_SCOPE_EXCEEDED

RULES = [{"reason": "outside_phase_tools", "repeat": 3, "action": "pause"},
         {"reason": "protected_path", "tools": ["Edit", "Write", "MultiEdit"], "test_file": True, "repeat": 1,
          "action": {"change_plan": "reproduce"}},
         {"reason": "budget_hint", "repeat": 2, "action": "escalate"}]


@pytest.fixture
def world(monkeypatch):
    calls = {"paused": [], "events": [], "restarted": [], "escalated": []}
    node = SimpleNamespace(id="fix", title="Minimal fix", config={"refusals": RULES})

    async def graph(db, run):
        return SimpleNamespace(nodes={"fix": node})

    async def pause(db, run, *, reason, actor_id, detail):
        run.status, run.pause_reason = "paused", reason
        calls["paused"].append((reason, detail))

    async def restart(db, run, node_id, *, actor_id):
        run.status, run.pause_reason = "running", None
        calls["restarted"].append(node_id)

    monkeypatch.setattr("app.services.workflow_runs.graph.graph_for_run", graph)
    monkeypatch.setattr("app.services.workflow_runs.limits.pause_run", pause)
    monkeypatch.setattr("app.services.workflow_runs.engine.restart_at", restart)
    monkeypatch.setattr(refusals, "record_event", lambda db, run, kind, **kw: calls["events"].append(kw["detail"]))
    monkeypatch.setattr("app.services.workflow_runs.size_class.escalate",
                        lambda db, run, *, cause: calls["escalated"].append(cause) or "")
    run = SimpleNamespace(current_node_id="fix", node_state={"entry": 4}, context={}, status="running",
                          pause_reason=None)
    return run, calls


@pytest.mark.asyncio
async def test_the_same_refused_command_three_times_pauses_with_the_proposal(world):
    run, calls = world
    bash = {"command": "flutter pub add drift"}
    assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=bash) == ""
    other = {"command": "dart run build_runner build"}
    assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=other) == ""
    assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=bash) == ""
    assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=bash) == "pause"
    reason, detail = calls["paused"][0]
    assert reason == PAUSE_PHASE_SCOPE_EXCEEDED and detail["intent"] == "Bash:flutter pub"
    assert "own story or a change plan" in detail["message"] and detail["resume"]["node_id"] == "fix"
    run.node_state = {"entry": 5}  # a new pass counts afresh
    assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=bash) == ""


@pytest.mark.asyncio
async def test_editing_a_protected_test_goes_back_to_reproduce_when_the_turn_ended(world):
    run, calls = world
    source = {"file_path": "lib/x.dart"}
    assert await refusals.react(None, run, tool="Edit", reason="protected_path", tool_input=source) == ""
    test = {"file_path": "/app/test/grind_test.dart"}
    assert await refusals.react(None, run, tool="Edit", reason="protected_path", tool_input=test,
                                message="'test/grind_test.dart' is a test file") == "change_plan"
    assert run.pause_reason == PAUSE_PHASE_SCOPE_EXCEEDED and calls["restarted"] == []
    assert await refusals.apply_pending_change_plan(None, run) is True
    assert calls["restarted"] == ["reproduce"]
    assert run.context["change_plan_reason"]["from"] == "fix" and "test file" in run.context["change_plan_reason"][
        "refusal"]
    assert await refusals.apply_pending_change_plan(None, run) is False  # once


@pytest.mark.asyncio
async def test_escalate_raises_the_size_class_and_a_class_without_one_pauses(world, monkeypatch):
    run, calls = world
    asked = {"command": "x y"}
    await refusals.react(None, run, tool="Bash", reason="budget_hint", tool_input=asked)
    assert await refusals.react(None, run, tool="Bash", reason="budget_hint", tool_input=asked) == "pause"
    assert calls["escalated"] == ["refusals:Bash:x y"]  # escalate answered "": no heavier class
    monkeypatch.setattr("app.services.workflow_runs.size_class.escalate", lambda db, run, *, cause: "M")
    run.node_state = {"entry": 6}
    await refusals.react(None, run, tool="Bash", reason="budget_hint", tool_input=asked)
    assert await refusals.react(None, run, tool="Bash", reason="budget_hint", tool_input=asked) == "escalate"


@pytest.mark.asyncio
async def test_a_phase_without_rules_reacts_never(world):
    run, _calls = world

    async def graph(db, run):
        return SimpleNamespace(nodes={"fix": SimpleNamespace(id="fix", title="t", config={})})

    import app.services.workflow_runs.graph as graph_module

    original = graph_module.graph_for_run
    graph_module.graph_for_run = graph
    try:
        for _ in range(5):
            assert await refusals.react(None, run, tool="Bash", reason="outside_phase_tools",
                                        tool_input={"command": "a b"}) == ""
    finally:
        graph_module.graph_for_run = original


def test_the_bug_seed_configures_both_cases_as_data():
    seeds = Path(refusals.__file__).parent / "seeds" / "phased_workflows.json"
    bug = next(item for item in json.loads(seeds.read_text(encoding="utf-8")) if item["key"] == "bug-fix-reproduction")
    fix = next(node for node in bug["definition"]["nodes"] if node["id"] == "fix")
    actions = [rule["action"] for rule in fix["config"]["refusals"]]
    # A refused protected test file goes back at once; a refused confirmed test only on its second refusal (the first
    # names the alternative).
    assert actions == ["pause", {"change_plan": "reproduce"}, {"change_plan": "reproduce"}]


@pytest.mark.asyncio
async def test_a_refused_command_is_kept_without_its_secret(world):
    """run.context keeps the refused requests for the pause's proposal: never a token of the command."""
    run, _calls = world
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    command = {"command": f"curl -H 'Authorization: Bearer {secret}' https://api.github.com/user"}
    await refusals.react(None, run, tool="Bash", reason="outside_phase_tools", tool_input=command)
    kept = [entry for entries in run.context[refusals.CONTEXT_KEY]["requests"].values() for entry in entries]
    assert kept and all(secret not in entry for entry in kept) and "curl" in kept[0]
