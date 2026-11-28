"""Run memory per repository and app (the agent never starts from zero)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.observability import workflow_metrics
from app.services.workflow_runs import records, run_memory
from app.services.workflow_runs.octryx.phase_brief import phase_brief
from app.services.workflow_runs.run_memory import capture, store
from app.services.workflow_runs.workspace.run_app import APP_SOURCE_INTAKE, app_context

T0 = datetime(2026, 11, 19, 12, 0, 0)


def _run(record_holder: dict, run_id: str = "run-1") -> SimpleNamespace:
    return SimpleNamespace(id=run_id, repository="github:acme/bench", project_id=None, current_node_id="fix",
                           node_state={"entry": 4, "entered_at": T0.isoformat()},
                           context={"app": app_context("e2e/node", APP_SOURCE_INTAKE)})


@pytest.fixture
def record(monkeypatch):
    found = SimpleNamespace(config_json={})

    async def record_of(_db, _run):
        return found

    monkeypatch.setattr(store, "record_of", record_of)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(records, "record_event", lambda _db, _run, kind, **kw: events.append((kind, kw["detail"])))
    found.events = events
    workflow_metrics.reset()
    return found


def _brief(run) -> str:
    phase = {"title": "Minimal fix", "node_id": "fix", "capability_class": "code_change", "checks": [],
             "path_rules": {"write": [], "create": []}, "protected_files": [], "how_to_run_tests": "x"}
    return phase_brief(run, {"phase": phase, "preparation": {}})


@pytest.mark.asyncio
async def test_what_one_run_verified_reaches_the_next_run_of_the_same_app(record):
    first = _run(record)
    capture.environment_failed(first, {"reason": "Error: Cannot find module 'node:test'"})
    await run_memory.pipeline_green(None, first, [{"command": "npm test", "exit_code": 0},
                                                  {"command": "npm run lint", "exit_code": 1}])
    memory = record.config_json["run_memory"]["e2e/node"]
    assert [entry["command"] for entry in memory["test_command"]] == ["npm test"]
    assert memory["environment_fix"][0]["error"] == "Error: Cannot find module 'node:test'"
    assert memory["environment_fix"][0]["ran"] == "npm test"
    assert workflow_metrics.RUN_MEMORY_LEARNED.series

    second = _run(record, "run-2")
    await run_memory.entered(None, second, SimpleNamespace(id="fix"))
    brief = _brief(second)
    assert "What earlier runs of this app learned" in brief
    assert "- Ran green in the platform's pipeline: `npm test`." in brief
    assert "Cannot find module 'node:test'" in brief
    [(kind, detail)] = record.events
    assert kind == "run_memory_used" and detail["counts"] == {"test_command": 1, "environment_fix": 1}


@pytest.mark.asyncio
async def test_a_refused_call_and_the_call_that_worked_next_are_kept_once(record):
    run = _run(record)
    denial = SimpleNamespace(id="ev-1", created_at=T0 + timedelta(seconds=5), detail={
        "tool": "Bash", "reason": "outside_phase_tools", "input": "cd e2e/node && npm test 2>&1 | tail -15",
        "message": "Phase 'Minimal fix' runs only plain test and read-only commands"})

    class Db:
        async def execute(self, _query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [denial]))

    hook = {"tool_name": "Bash", "tool_input": {"command": "npm test"}}
    await run_memory.denial_answered(Db(), run, hook)
    await run_memory.denial_answered(Db(), run, {"tool_name": "Bash", "tool_input": {"command": "npm test -- x"}})
    [entry] = record.config_json["run_memory"]["e2e/node"]["denial_alternative"]
    assert (entry["refused"], entry["worked"], entry["reason"]) == (
        "cd e2e/node && npm test 2>&1 | tail -15", "Bash: npm test", "outside_phase_tools")
    await run_memory.entered(None, run, SimpleNamespace(id="fix"))
    assert "What worked instead: `Bash: npm test`" in _brief(run)


@pytest.mark.asyncio
async def test_another_app_and_a_workspace_that_switched_it_off_get_nothing(record, monkeypatch):
    await run_memory.pipeline_green(None, _run(record), [{"command": "npm test", "exit_code": 0}])
    other = _run(record, "run-3")
    other.context = {"app": app_context("e2e/python", APP_SOURCE_INTAKE)}
    await run_memory.entered(None, other, SimpleNamespace(id="fix"))
    assert "What earlier runs" not in _brief(other)

    async def off(_db, _run):
        return False

    monkeypatch.setattr(store, "_enabled", off)
    same = _run(record, "run-4")
    await run_memory.entered(None, same, SimpleNamespace(id="fix"))
    assert "What earlier runs" not in _brief(same)


@pytest.mark.asyncio
async def test_a_too_long_output_and_its_short_form_reach_the_next_brief(record, monkeypatch):
    run = _run(record)

    tools = [SimpleNamespace(tool="Bash", chars=21 * 1024, call=3, label="flutter test --reporter json"),
             SimpleNamespace(tool="Bash", chars=900, call=7, label="flutter test 2>&1 | tail -30"),
             SimpleNamespace(tool="Read", chars=30 * 1024, call=8, label="lib/main.dart")]
    await capture.remember_large(None, run, tools)
    [entry] = record.config_json["run_memory"]["e2e/node"]["large_output"]
    assert (entry["command"], entry["kb"], entry["shorter"]) == (
        "flutter test --reporter json", 21, "flutter test 2>&1 | tail -30")
    second = _run(record, "run-2")
    await run_memory.entered(None, second, SimpleNamespace(id="fix"))
    phase = {"title": "Story", "node_id": "fix", "capability_class": "code_change", "checks": [],
             "path_rules": {"write": [], "create": []}, "protected_files": [], "how_to_run_tests": "x",
             "pipeline_after": "note"}
    brief = phase_brief(second, {"phase": phase, "preparation": {}})
    assert "so print only the result, e.g. `flutter test 2>&1 | tail -30`" in brief
    assert "- `flutter test --reporter json` printed 21 KB in an earlier run; `flutter test 2>&1 | tail -30` was " \
           "enough." in brief


def test_without_a_pipeline_after_the_phase_the_agent_is_never_asked_for_less_output():
    phase = {"title": "Reproduce", "node_id": "repro", "capability_class": "code_change", "checks": [],
             "path_rules": {"write": [], "create": []}, "protected_files": [], "how_to_run_tests": "x"}
    environment = {"source": "environment_file", "test": "flutter test", "app_folder": "app"}
    assert "Output:" not in phase_brief(None, {"phase": phase, "preparation": {"environment": environment}})
    piped = phase_brief(None, {"phase": {**phase, "pipeline_after": "note"},
                               "preparation": {"environment": environment}})
    assert "e.g. `flutter test 2>&1 | tail -30`" in piped


@pytest.mark.asyncio
async def test_the_refused_and_the_working_call_are_kept_without_their_secrets(record):
    run = _run(record)
    secret = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"
    denial = SimpleNamespace(id="ev-9", created_at=T0 + timedelta(seconds=5), detail={
        "tool": "Bash", "reason": "outside_phase_tools", "input": f"GITHUB_TOKEN={secret} npm run e2e",
        "message": "Phase 'Minimal fix' runs only plain test and read-only commands"})

    class Db:
        async def execute(self, _query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [denial]))

    await run_memory.denial_answered(Db(), run, {"tool_name": "Bash", "tool_input": {
        "command": f"curl -H 'Authorization: Bearer {secret}' localhost:3000/health"}})
    [entry] = record.config_json["run_memory"]["e2e/node"]["denial_alternative"]
    assert secret not in entry["refused"] and secret not in entry["worked"]
    assert "npm run e2e" in entry["refused"] and "localhost:3000/health" in entry["worked"]
