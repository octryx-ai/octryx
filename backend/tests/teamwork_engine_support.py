"""Shared helpers for the test_teamwork_engine_* modules."""

from __future__ import annotations

import copy
import uuid

import pytest

from app.models import Session, WorkflowRunSession
from app.services.workflow_runs import teamwork
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.phase_outputs import submit_output
from app.services.workflow_runs.records import RUN_METADATA_KEY, start_run
from app.services.workflow_runs.run_sessions import new_bound_session
from app.services.workflow_runs.teamwork import item_results
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace


def _role() -> dict:
    role = copy.deepcopy(PHASE)
    role["workflow_contract"].update(capability_class="change", checks=[
        {"type": "tool_called", "params": {"tools": ["edit_workspace_file"]}, "blocking": True,
         "description": "The item's files were written"}])
    role["tool_policy"]["allowlist"] = ["read_workspace_file", "edit_workspace_file"]
    return role


def team_definition(*, roles: dict | None = None, replan_kind: str = "loop", plan_output: str = "work_plan",
                    parallel: bool | None = None) -> dict:
    plan = copy.deepcopy(PHASE)
    plan["output"] = plan_output
    plan["workflow_contract"]["checks"] = [{"type": "tool_called", "params": {"tools": ["submit_work_plan"]},
                                            "blocking": True, "description": "The work plan was submitted"}]
    plan["tool_policy"]["allowlist"] = ["knowledge_search", "submit_work_plan"]
    config = {"plan": "plan", "roles": roles if roles is not None else {"backend": _role(), "frontend": _role()}}
    if parallel is not None:
        config["parallel"] = parallel
    replan = {"id": "replan", "source_node_id": "work", "target_node_id": "plan", "when": "replan",
              "kind": replan_kind, "label": "Re-plan"}
    if replan_kind == "loop":
        replan["max_iterations"] = 3
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "plan", "type": "phase", "label": "Plan the work", "config": plan},
                  {"id": "work", "type": "parallel_work", "label": "Parallel work", "config": config},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "e1", "source_node_id": "start", "target_node_id": "plan"},
                  {"id": "e2", "source_node_id": "plan", "target_node_id": "work"},
                  {"id": "e3", "source_node_id": "work", "target_node_id": "done", "when": "done"}, replan],
    }


def item(key: str, *, role: str = "backend", depends_on=None, paths=None, **extra) -> dict:
    return {"id": key, "title": f"Build {key}", "role": role, "depends_on": depends_on or [],
            "paths": [*(paths or [f"{key}/**"]), f"tests/test_{key}.py"], "instructions": f"Build {key}.",
            "proofs": [f"tests/test_{key}.py::test_{key}"], **extra}


# --- the scheduler with a fake executor ----------------------------------------------------------------------------


class FakeExecutor:
    name = "fake"

    def __init__(self):
        self.started: list[tuple[str, str | None]] = []
        self.conflicts: set[str] = set()
        self.finished = 0
        self.capacity_value: int | None = None

    def capacity(self, run):
        return self.capacity_value

    async def start(self, db, run, item):
        self.started.append((item["id"], item.get("session_id")))
        session = await db.get(Session, item["session_id"]) if item.get("session_id") else None
        if session is None:
            session = Session(id=str(uuid.uuid4()), user_id=run.requested_by, project_id=run.project_id,
                              agent_type="coding", status="active", origin="sub_agent",
                              metadata_={teamwork.ITEM_METADATA_KEY: {"run_id": run.id, "key": item["id"],
                                                                      "node_id": run.current_node_id},
                                         RUN_METADATA_KEY: run.id})
            db.add(session)
            await db.flush()
            db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role=teamwork.ROLE_ITEM,
                                      runtime="chat", active=True))
            await db.flush()
        return {"status": "running", "session_id": session.id}

    async def merge(self, db, run, item):
        conflict = item["id"] in self.conflicts
        await item_results.merge_reported(db, run, key=item["id"], merged=not conflict,
                                       conflicts=[f"{item['id']}/shared.ts"] if conflict else None,
                                       merged_sha=None if conflict else f"sha-{item['id']}")

    async def finish(self, db, run):
        self.finished += 1


@pytest.fixture
def fake(tmp_path):
    executor = FakeExecutor()
    executor.copy = tmp_path / "copy"
    (executor.copy / ".git").mkdir(parents=True)  # the run's working copy a change phase needs on the server

    async def factory(db, run):
        return executor

    teamwork.register_executor("fake", factory, first=True)
    yield executor
    teamwork._EXECUTORS.pop("fake", None)


async def planned_run(db, items: list[dict], *, copy_dir, definition: dict | None = None):
    """A run whose coordinator submitted ``items`` and passed: the run is at the parallel_work node."""
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or team_definition()),
                          project_id=workspace_id)
    session = await new_bound_session(db, run, admin)
    run.context = {**run.context, "local_path": str(copy_dir)}
    resolution = await run_turn_resolution(db, session, user_message="Plan the story.")
    recorded = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/search", "items": items},
                                   session_id=session.id)
    assert recorded["state"] == "recorded", recorded
    await phase_turn(db, session.id, resolution, ["submit_work_plan"])
    return run, session


def items_of(run) -> dict:
    return dict(teamwork.work_of(run)["items"])


async def finish_item(db, run, key: str, *, value: str = "done", tools=("edit_workspace_file",)) -> dict:
    """The item's real turn: its resolution, its recorded result, the turn-end checks."""
    session = await db.get(Session, items_of(run)[key]["session_id"])
    resolution = await run_turn_resolution(db, session, user_message="Build it.")
    assert resolution["workflow_run"].get("item") == key, resolution.get("unmatched_reason")
    answer = await submit_output(db, run, "submit_phase_result", {"value": value, "summary": f"{key} {value}"},
                                 session_id=session.id)
    assert answer["state"] == "recorded", answer
    await ended_turn(db, session.id, resolution, [*tools, "submit_phase_result"])
    return resolution


async def ended_turn(db, session_id: str, resolution: dict, tools: list[str]) -> None:
    """A turn's end after its one reminder was used: failing checks are recorded instead of reminded again."""
    from app.agent.loops.response._loop_workflow_checks import REMINDER_MARKER, handle_workflow_checks_guard
    from app.services.prompt_catalog import prompt_set_scope, seed_prompt_set
    from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    async def persist_turn_trace(**_kwargs):
        return None

    reminded = [{"role": "system", "content": f"{REMINDER_MARKER} checks"}] * 3
    with prompt_set_scope(seed_prompt_set()):
        await handle_workflow_checks_guard(
            db=db, session_id=session_id, runtime={"provider_name": "test"}, response={"usage": {}},
            request_messages=[], messages=list(reminded), context_snapshot={}, runtime_attempts=[],
            runtime_settings={}, usage_model="m", content="Done.", tool_calls=None, has_followup_steps=False,
            sub_agent_depth=0, request_analysis={ROUTING_RESOLUTION_KEY: resolution},
            turn_tool_history=[{"tool_name": name, "status": "success", "result": {}} for name in tools],
            persist_turn_trace=persist_turn_trace)
