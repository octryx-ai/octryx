"""Shared helpers for the test_workflow_run_pipeline_* modules."""

from __future__ import annotations

import copy

from app.services.workflow_runs import pipeline
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace

COMMANDS = [".venv/bin/python -m pytest -q --ignore=tests/system", ".venv/bin/python -m pytest -v tests/system"]


def _definition() -> dict:
    work = copy.deepcopy(PHASE)
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "work", "type": "phase", "label": "Work", "config": work},
            {"id": "pipeline", "type": "platform_action", "label": "CI", "config": {"action": "pipeline.run"}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "work"},
            {"id": "b", "source_node_id": "work", "target_node_id": "pipeline"},
            {"id": "c", "source_node_id": "pipeline", "target_node_id": "done", "when": "succeeded"},
            {"id": "d", "source_node_id": "pipeline", "target_node_id": "work", "when": "failed", "kind": "loop",
             "max_iterations": 3},
        ],
    }


async def _at_pipeline(db, monkeypatch, runtime="device", commands_declared=None):
    declared = list(COMMANDS if commands_declared is None else commands_declared)

    async def commands(_db, _run):
        return list(declared), [".venv/bin"], declared[-1] if len(declared) > 1 else ""

    async def device(_db, _run):
        return runtime

    async def no_turn(_db, _run, _node):
        return None

    monkeypatch.setattr(pipeline, "commands_for", commands)
    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", device)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", no_turn)
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition()),
                          project_id=workspace_id, session=session)
    resolution = await run_turn_resolution(db, session, user_message="Build it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    return run, session


def _report(run, codes):
    view = pipeline.contract_view(run)
    return {"node_id": view["node_id"], "entry": view["entry"],
            "results": [{"command": command, "exit_code": code, "seconds": 3.0, "output_tail": f"out {n}",
                         "junit_xml": None} for n, (command, code) in enumerate(zip(view["commands"], codes))]}


TASKS = [{"id": "T1", "text": "search", "proof": "tests/test_search.py::test_text_search",
          "proofs": ["tests/test_search.py::test_text_search"], "status": "open"},
         {"id": "T2", "text": "cards", "proof": "tests/test_search.py::test_cards",
          "proofs": ["tests/test_search.py::test_cards"], "status": "open"}]


def _fix_with_pipeline() -> dict:
    from tests.workflow_run_octryx_support import _fix_definition

    definition = _fix_definition(protect=False)
    definition["nodes"] = [node for node in definition["nodes"] if node["id"] != "green"] + [
        {"id": "pipeline", "type": "platform_action", "label": "CI", "config": {"action": "pipeline.run"}}]
    definition["edges"] = [
        {"id": "1", "source_node_id": "start", "target_node_id": "fix"},
        {"id": "2", "source_node_id": "fix", "target_node_id": "pipeline"},
        {"id": "3", "source_node_id": "pipeline", "target_node_id": "done", "when": "succeeded"},
        {"id": "4", "source_node_id": "pipeline", "target_node_id": "fix", "when": "failed", "kind": "loop",
         "max_iterations": 3}]
    return definition


async def _device_run(db, definition, monkeypatch):
    from tests.server_build_lock import lift_server_build_lock
    from tests.workflow_run_octryx_support import _bound_run

    lift_server_build_lock(monkeypatch)

    run, gateway, key, workspace_id = await _bound_run(db, definition)
    run.context = {**run.context, "task_list": TASKS, "workspace_preparation": {
        "state": "ready", "spec": {"environment": {"source": "declared", "test": COMMANDS[0]}}}}
    await db.flush()
    return run, gateway, key, workspace_id


FILE = "coffee/web/claude/.octryx/environment.json"


FILE_ENV = {"test": ".venv/bin/python -m pytest -v tests/unit", "system_test": ".venv/bin/python -m pytest -v tests/system",
            "setup": ["python3 -m venv .venv"], "path": [".venv/bin"]}


async def _at_file_pipeline(db, monkeypatch):
    async def pointer(_db, _run):
        return {"file": FILE, "app_folder": "coffee/web/claude"}

    async def no_commands(_db, _run):
        raise AssertionError("an environment file never takes the record's commands")

    run, session = await _at_pipeline(db, monkeypatch)  # the record declares COMMANDS
    monkeypatch.setattr(pipeline, "environment_file_for", pointer)
    monkeypatch.setattr(pipeline, "commands_for", no_commands)
    # A second pass through the step, now with the pointer.
    run.context = {**dict(run.context or {}), pipeline.CONTEXT_KEY: {}}
    from app.services.workflow_runs.graph import graph_for_run

    graph = await graph_for_run(db, run)
    await pipeline.start(db, run, graph.nodes["pipeline"])
    return run, session


def _file_report(run, account, codes=()):
    view = pipeline.contract_view(run)
    commands = account.get("commands") or []
    return {"node_id": view["node_id"], "entry": view["entry"], "head": "a" * 40, "tree": "",
            "environment_file": account,
            "results": [{"command": command, "exit_code": code, "seconds": 1.0, "output_tail": "", "junit_xml": None}
                        for command, code in zip(commands, codes)]}
