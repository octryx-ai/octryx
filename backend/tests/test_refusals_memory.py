"""Refusals inform first and are reused (block less, never start from zero):
(a) refusals count per run and intent, across entries of the phase, and the refusal names the concrete alternative;
(b) a refused confirmed test reaches the fix phase's refusal rule; (c) an unfinished or stalled pass goes on in the
same pass with what is missing; (d) the stall threshold is workflow data."""

from __future__ import annotations

import json

import pytest

from app.services.workflow_runs.refusals import _matches, react, times_refused
from app.services.workflow_runs.seeding import SEEDS_PATH
from tests.phased_workflow_fixtures import admin_user, publish_phased, run_workspace
from tests.test_workflow_size_class_merge import _definition

SHELL = {"command": "cd e2e/node && npm test 2>&1 | tail -15"}


async def _run(db, classes: dict, **write_config):
    from app.services.workflow_runs.records import start_run

    definition = _definition(classes)
    write = next(node for node in definition["nodes"] if node["id"] == "write")
    write["config"].update(write_config)
    workspace_id = await run_workspace(db, await admin_user(db))
    return await start_run(db, user=await admin_user(db), workflow_key=await publish_phased(db, definition),
                           project_id=workspace_id)


@pytest.mark.asyncio
async def test_a_refusal_counts_per_run_across_entries_and_says_what_to_do_instead(db):
    from app.services.workflow_runs.engine import restart_at
    from app.services.workflow_runs.refusal_hints import instead

    rule = {"reason": "outside_phase_tools", "repeat": 2, "action": "pause"}
    run = await _run(db, {}, refusals=[rule])
    run.context = {**dict(run.context or {}), "app": {"path": "e2e/node"},
                   "contract_pin": {"file": "e2e/node/.octryx/environment.json", "sha256": "sha256:" + "c" * 64,
                                    "commands": {"test": "npm test"}}}
    assert await react(db, run, tool="Bash", reason="outside_phase_tools", tool_input=SHELL) == ""
    first = instead(run, reason="outside_phase_tools", tool="Bash", tool_input=SHELL)
    assert "`npm test`" in first and "`e2e/node`" in first and "refused" not in first  # the alternative at once
    await restart_at(db, run, "write", actor_id=None)  # a new entry of the phase (a change of plan)
    assert await react(db, run, tool="Bash", reason="outside_phase_tools", tool_input=SHELL) == "pause"
    assert times_refused(run, "Bash", SHELL) == 2
    assert "refused 2 times" in instead(run, reason="outside_phase_tools", tool="Bash", tool_input=SHELL)


def test_a_refused_confirmed_test_reaches_the_fix_phases_rule():
    flows = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    fix = next(node for node in next(flow for flow in flows if flow["key"] == "bug-fix-reproduction")
               ["definition"]["nodes"] if node["id"] == "fix")
    rules = [rule for rule in fix["config"]["refusals"] if rule.get("test_file")]
    confirmed = [rule for rule in rules if _matches(rule, "Edit", "confirmed_test_protected",
                                                    {"file_path": "tests/test_split.py"})]
    # The first refusal names what to do instead (change the code); the second sends the run back to reproduce.
    assert [rule["repeat"] for rule in confirmed] == [2]
    assert any(_matches(rule, "Edit", "protected_path", {"file_path": "tests/test_split.py"}) for rule in rules)


@pytest.mark.asyncio
async def test_a_stalled_pass_goes_on_in_the_same_pass_with_what_is_missing(db):
    from app.services.workflow_runs.octryx.gate_failure import current
    from app.services.workflow_runs.octryx.stop_stall import _stalled

    run = await _run(db, {})
    missing = "The confirmed failing test was not submitted"
    assert await _stalled(db, run, "write", missing, 4) is False
    assert await _stalled(db, run, "write", missing, 4) is True  # the default: the second identical stop
    assert run.node_state["pause"]["resume"] == {"kind": "continue", "node_id": "write"}
    assert missing in current(run, "write")["failed"]  # the next prompt names it first


@pytest.mark.asyncio
async def test_the_stall_threshold_is_the_workflows_data(db):
    from app.services.workflow_runs.octryx.stop_stall import _stalled
    from app.services.workflow_runs.size_class.schema import size_class_errors

    run = await _run(db, {"stall_after": 3})
    for _ in range(2):
        assert await _stalled(db, run, "write", "x", 1) is False
    assert await _stalled(db, run, "write", "x", 1) is True
    assert any("stall_after" in error["message"] for error in size_class_errors(
        {"default": "small", "rules": [], "classes": {"small": {"stall_after": 0}}}, None))
