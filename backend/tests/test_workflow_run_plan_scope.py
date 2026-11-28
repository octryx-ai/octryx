"""Expensive paths and the approved plan's scope: a write to an expensive path without an approved plan, or outside
an approved plan's paths, is refused and the run waits for a person; the approval widens the scope."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.devices.device_runs_keys import DeviceRunsPolicyError, normalize_device_runs
from app.services.mcp_workflow_run_tools import PHASE_OUTPUT_MCP_HANDLERS
from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.phase_outputs import OUTPUT_BY_TOOL, OUTPUTS_KEY
from app.services.workflow_runs.plan_scope import (
    DEFAULT_EXPENSIVE_PATHS,
    classes_of,
    expensive_classes,
    refusal,
    validate_change_plan,
)
from app.tools.definitions.workflow_outputs import WORKFLOW_OUTPUT_DEFINITIONS
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import ROOT, _bound_run, _decide, _fix_definition, _hook

pytestmark = pytest.mark.usefixtures("scripted_pool")

MIGRATION = "backend/alembic/versions/0002_x.py"
NEW_FILE = {"target_exists": False, "shadows_installed": False}


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.mark.parametrize(("path", "classes"), [
    (MIGRATION, ["migrations"]), ("app/db/migrations/0001.py", ["migrations"]), ("schema.sql", ["migrations"]),
    ("app/auth/login.py", ["auth"]), ("api/openapi.yaml", ["public_api"]), ("proto/orders.proto", ["public_api"]),
    ("schema.graphql", ["public_api"]), ("app/api/routes/x.py", []), ("app/routes/y.py", []),
    ("Dockerfile", ["infra"]), ("services/web/Dockerfile.dev", ["infra"]), ("deploy/values.yaml", ["infra"]),
    (".github/workflows/ci.yml", ["infra"]), ("src/app.py", []),
])
def test_default_classes_name_contract_files_not_everyday_backend_work(path, classes):
    assert classes_of(path, expensive_classes(None)) == classes


def test_stored_classes_win_and_an_empty_dict_means_none():
    assert expensive_classes(None) == DEFAULT_EXPENSIVE_PATHS
    assert expensive_classes({}) == DEFAULT_EXPENSIVE_PATHS
    assert expensive_classes({"expensive_paths": {}}) == {}
    custom = expensive_classes({"expensive_paths": {"db": ["**/schema/**"]}})
    assert custom == {"db": ["**/schema/**"]}
    assert classes_of("app/schema/a.py", custom) == ["db"] and classes_of(MIGRATION, custom) == []


@pytest.mark.parametrize(("raw", "problem"), [
    ({"paths": ["src/**"]}, "parts:"),
    ({"parts": ["x"]}, "paths:"),
    ({"parts": ["x"], "paths": ["../x"]}, "'../x' is not a relative path"),
    ({"parts": ["x"], "paths": ["/x"]}, "'/x' is not a relative path"),
    ({"parts": ["x"], "paths": ["src/**"], "expensive": ["payments"]}, "'payments' is not one of"),
    ({"parts": ["x"], "paths": ["backend/alembic/**"]}, "the paths touch 'migrations'"),
])
def test_a_change_plan_names_parts_relative_paths_and_every_class_it_touches(raw, problem):
    _record, problems = validate_change_plan(raw, expensive_classes(None))
    assert any(problem in item for item in problems), problems


def test_without_the_workspace_classes_an_unknown_class_name_is_not_refused():
    assert validate_change_plan({"parts": ["x"], "paths": ["src/**"], "expensive": ["payments"]})[1] == []


def test_a_clean_change_plan_is_recorded_as_lists():
    record, problems = validate_change_plan({"parts": ["Add a column"], "paths": ["backend/alembic/**", "src/**"],
                                             "expensive": ["migrations"], "risks": "not a list"})
    assert problems == []
    assert record["paths"] == ["backend/alembic/**", "src/**"] and record["risks"] == []


CLASSES = expensive_classes(None)
NO_PLAN = {"plan": {}, "approved": False, "paths": [], "granted": []}


@pytest.mark.parametrize(("names", "state", "expected"), [
    (["src/a.py"], NO_PLAN, ("", "", [])),
    ([MIGRATION], NO_PLAN, ("expensive_path", MIGRATION, ["migrations"])),
    ([MIGRATION], {**NO_PLAN, "plan": {"expensive": ["migrations"]}}, ("plan", MIGRATION, ["migrations"])),
    (["docs/x.md"], {"plan": {"paths": ["src/**"]}, "approved": True, "paths": ["src/**"], "granted": []},
     ("outside_plan", "docs/x.md", [])),
    ([MIGRATION], {"plan": {"expensive": ["migrations"]}, "approved": True, "paths": ["backend/alembic/**"],
                   "granted": []}, ("", "", [])),
    ([MIGRATION], {**NO_PLAN, "granted": [MIGRATION]}, ("", "", [])),
])
def test_refusal_names_the_first_path_the_scope_refuses(names, state, expected):
    assert refusal(names, state, CLASSES) == expected


def _write(path: str, **extra) -> dict:
    return {**_hook("Write", file_path=f"{ROOT}/{path}", content="x", **extra), "workflow_run_facts": NEW_FILE}


async def _build_run(db):
    # A build phase without the confirmed-test rules: it may create files anywhere the scope allows.
    return await _bound_run(db, _fix_definition(protect=False))


async def _events(db, run, kind: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind))).scalars())


@pytest.mark.asyncio
async def test_a_migration_without_a_plan_pauses_the_run_until_a_person_approves_the_path(db):
    run, gateway, key, workspace_id = await _build_run(db)
    assert (await _decide(db, gateway, key, workspace_id, _write("src/app.py")))["decision"] == "allow"

    answer = await _decide(db, gateway, key, workspace_id, _write(MIGRATION))
    assert (answer["decision"], answer["reason"]) == ("deny", "needs_approval")
    await db.refresh(run)
    pause = run.node_state["pause"]
    assert run.status == "paused" and run.pause_reason == "needs_approval"
    assert (pause["kind"], pause["path"], pause["classes"]) == ("expensive_path", MIGRATION, ["migrations"])

    admin = await admin_user(db)
    actions = {item["key"]: item for item in await available_actions(db, run, access="write", user=admin)}
    assert actions["continue"]["label"] == f"Approve {MIGRATION}"
    assert actions["change_plan"]["label"] == "Change the plan"

    await perform_action(db, run, user=admin, body={"action": "continue"})
    await db.refresh(run)
    assert run.status == "running"
    assert MIGRATION in run.context["plan_scope"]["paths"]
    [event] = await _events(db, run, "plan_scope_approved")
    assert event.detail == {"kind": "expensive_path", "path": MIGRATION, "classes": ["migrations"]}
    assert (await _decide(db, gateway, key, workspace_id, _write(MIGRATION)))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_codex_patch_split_per_file_meets_the_same_refusal(db):
    # The launcher splits Codex's apply_patch into one Write/Edit per file (codex_hook_input.split_apply_patch):
    # the backend only ever sees that split form.
    run, gateway, key, workspace_id = await _build_run(db)
    answer = await _decide(db, gateway, key, workspace_id, _write(MIGRATION, codex_patch=True))
    assert (answer["decision"], answer["reason"]) == ("deny", "needs_approval")
    await db.refresh(run)
    assert run.pause_reason == "needs_approval" and run.node_state["pause"]["path"] == MIGRATION


@pytest.mark.asyncio
async def test_an_approved_plan_refuses_a_write_outside_its_paths(db):
    run, gateway, key, workspace_id = await _build_run(db)
    record, problems = validate_change_plan({"parts": ["Totals"], "paths": ["src/**"]})
    assert problems == []
    run.context = {**dict(run.context or {}), OUTPUTS_KEY: {"change_plan": {"record": record}}}
    await db.flush()

    assert (await _decide(db, gateway, key, workspace_id, _write("src/app.py")))["decision"] == "allow"
    answer = await _decide(db, gateway, key, workspace_id, _write("docs/x.md"))
    assert (answer["decision"], answer["reason"]) == ("deny", "needs_approval")
    await db.refresh(run)
    assert (run.node_state["pause"]["kind"], run.node_state["pause"]["path"]) == ("outside_plan", "docs/x.md")


def test_device_runs_accepts_expensive_path_classes_and_refuses_bad_shapes():
    assert normalize_device_runs({"expensive_paths": {"db": ["**/migrations/**"]}}, "p")["expensive_paths"] == {
        "db": ["**/migrations/**"]}
    assert normalize_device_runs({"expensive_paths": None}, "p")["expensive_paths"] is None
    for bad in (["**/x"], {"Bad Name": ["x"]}, {"db": "**/x"}, {"db": [""]}, {"db": [1]}):
        with pytest.raises(DeviceRunsPolicyError) as refused:
            normalize_device_runs({"expensive_paths": bad}, "p")
        assert refused.value.reason == "invalid_expensive_paths"


def test_submit_change_plan_is_a_registered_phase_output():
    assert OUTPUT_BY_TOOL["submit_change_plan"].kind == "change_plan"
    assert "submit_change_plan" in PHASE_OUTPUT_MCP_HANDLERS
    assert WORKFLOW_OUTPUT_DEFINITIONS["submit_change_plan"]
