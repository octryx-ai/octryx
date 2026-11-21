"""On the server, ``workspace.prepare`` prepares a test environment only for a workflow that builds or tests.

A workflow without a build or test step (spec writing, triage) gets its branch prepared and its environment reported
``not_needed``: the readiness probes of a repository's declared Python test would only meet the server-build guard
and pause the run ``environment_not_ready`` (the demo's spec writing stopped there). A workflow that builds or tests
still runs the probes, and on the server the guard still refuses them; such a workflow is refused at start anyway
(``test_workflow_run_server_build_lock``).
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.workspace.preparation import decide
from app.services.workflow_runs.workspace.recovery import prepare_on_server
from app.services.workflow_runs.workspace.server_prepare import READY_BRANCH_STATES
from app.services.workflow_runs.workspace.spec import probes
from tests.devices.device_support import device_with_grant, enable_device_runs
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import PHASE, admin_user, phased_definition, publish_phased

FOLDER = "/Users/dev/work/pay"
PYTHON_TESTS = {"probes": probes({"test": "python3 -m unittest"})}


def _repository(root: Path) -> Path:
    """A working copy on ``main`` with one commit, its tests declared as ``python3 -m unittest``."""
    root.mkdir()
    for argv in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.test"], ["config", "user.name", "t"]):
        subprocess.run(["git", *argv], cwd=root, check=True)
    (root / "test_shop.py").write_text("import unittest\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
    return root


def _building_definition() -> dict:
    definition = phased_definition()
    phase = copy.deepcopy(PHASE)
    phase["workflow_contract"]["capability_class"] = "change"
    phase["tool_policy"]["allowlist"] = [*phase["tool_policy"]["allowlist"], "run_test_suite"]
    definition["nodes"][1] = {**definition["nodes"][1], "label": "Fix and test", "config": phase}
    return definition


async def _run(db, definition: dict, target: dict, repository: Path):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    if target["kind"] == "device":
        device, _ = await device_with_grant(db, admin, name="Mac", folders=[FOLDER], profiles=["governed"])
        target = {**target, "device_id": device.id}
    key = await publish_phased(db, definition)
    run = await start_run(db, user=admin, workflow_key=key, project_id=project.id, runtime_target=target,
                          session=await new_chat_session(db, admin, project.id))
    run.context = {**dict(run.context or {}), "local_path": str(repository)}
    return run


@pytest.mark.asyncio
async def test_spec_writing_on_the_server_skips_the_environment_of_a_repository_with_python_tests(db, tmp_path):
    spec_writing = next(seed["definition"] for seed in seed_definitions() if seed["key"] == "spec-writing")
    run = await _run(db, spec_writing, {"kind": "server"}, _repository(tmp_path / "shop"))

    report = await prepare_on_server(db, run, {"branch": "main", "environment": PYTHON_TESTS})

    assert report["branch"]["state"] in READY_BRANCH_STATES, report["branch"]
    assert report["environment"]["state"] == "not_needed"
    assert report["environment"]["probes"] == []  # nothing ran, nothing met the server-build guard
    assert decide(report).ok


@pytest.mark.asyncio
async def test_a_workflow_that_builds_still_checks_its_environment_and_the_server_refuses_it(db, tmp_path):
    device = {"kind": "device", "folder": FOLDER, "profile": "governed"}
    run = await _run(db, _building_definition(), device, _repository(tmp_path / "shop"))

    report = await prepare_on_server(db, run, {"branch": "main", "environment": PYTHON_TESTS})

    assert report["environment"]["state"] == "not_ready"
    assert report["environment"]["probes"] and not report["environment"]["probes"][0]["ok"]
    outcome = decide(report)
    assert not outcome.ok and outcome.failure_class == "environment_not_ready"
