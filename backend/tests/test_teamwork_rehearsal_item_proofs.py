"""Merged items survive the coordinator's turns to the pipeline, and an item's stop judges only its own proofs."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from app.models import DeviceJob
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.teamwork import device_work_state
from tests.teamwork_device_support import _gateway_session, _hub, admitted  # noqa: F401 - fixtures
from tests.teamwork_rehearsal_support import (  # noqa: F401
    _DEVICE_RUN,
    BRANCH,
    FILES,
    PLAN,
    Device,
    _git,
    _item,
    _items,
    _launcher,
    _story_run,
    agent_checks_pass,
    coordinator_plans,
)
from tests.test_team_delivery import actions  # noqa: F401 - ``actions`` is a fixture

pytestmark = pytest.mark.usefixtures("admitted", "_hub", "agent_checks_pass")


def _tracked(folder: Path) -> set[str]:
    return set(_git(folder, "ls-files").splitlines())


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_merged_items_survive_the_coordinators_turns_the_work_plan_commits_and_the_pipeline(db, tmp_path):
    """A main-thread job must not prepare the folder by checking out the coordinator's last WIP tree over it when that
    tree was taken before the items merged: the merged files would leave the working tree, the work-plan commits
    would commit their deletion, the next items would branch without ``src/`` and report blocked, and the pipeline
    would find no tests until the loop limit. The real launcher code end to end: prepare (WIP restore) before each
    main-thread job, the WIP pushed after each coordinator turn, the work-plan commits, the item worktrees, a replan
    for a blocked item."""
    _launcher()  # the launcher's package on the path
    from octryx_claude.run_wip import push_run_wip

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", BRANCH, str(origin)], check=True)
    _git(main, "remote", "add", "origin", str(origin))  # where the run's WIP travels (``octryx-wip/<run id>``)
    main_gateway = await _gateway_session(db, admin, project.id, "key-main")
    device_side = Device(db, admin, project, run, main, base)
    plan = [*PLAN[:2], PLAN[3]]  # two items side by side, the system tests after both
    merged = [FILES["core-domain"], FILES["frontend-shell"]]

    async def coordinator_turn(note: str) -> None:
        await device_side.prepares_main(main_gateway)
        (main / "docs" / "stories").mkdir(parents=True, exist_ok=True)
        (main / "docs" / "stories" / "OCX-91.md").write_text(note)  # the coordinator's own file
        await coordinator_plans(db, admin, project, thread, run, plan=plan)
        assert push_run_wip(str(main), run.id)["state"] == "pushed"  # its turn's end (``device_jobs``)

    def assert_merged_everywhere(*folders: Path) -> None:
        for folder in folders:
            for name in merged:
                assert (folder / name).is_file(), f"{name} missing in {folder}"
        deleted = _git(main, "log", "--diff-filter=D", "--name-only", "--format=", f"{base}..HEAD").split()
        assert not set(deleted) & set(merged), deleted  # no platform commit ever deleted an item's file

    await coordinator_turn("plan v1\n")  # WIP 1: taken on the base, before any item merged
    await device_side.git_work(main_gateway)
    for key in ("core-domain", "frontend-shell"):
        await device_side.item_turn(key)
        await device_side.git_work(main_gateway)  # each merge's job prepares the folder first (WIP 1 restored)
    if run.context[device_work_state.GIT_KEY].get("sent"):
        await device_side.git_work(main_gateway)
    system = _items(run)["flow-wiring"]
    assert system["status"] == "running"
    assert_merged_everywhere(main, Path(system["path"]))  # the plan commit kept them; the item branched with them

    # The system tests are blocked: the run goes back to the coordinator, whose turn restores its WIP again.
    await device_side.item_turn("flow-wiring", value="blocked")
    assert _items(run)["flow-wiring"]["status"] == "blocked" and run.current_node_id == "plan"
    await coordinator_turn("plan v2: the system tests use the merged server\n")
    assert_merged_everywhere(main)
    assert run.current_node_id == "work"
    [op] = run.context[device_work_state.GIT_KEY]["sent"]["ops"]
    assert (op["key"], op.get("sync")) == ("flow-wiring", True)  # branched again, with the merged work
    await device_side.git_work(main_gateway)
    system = _items(run)["flow-wiring"]
    assert system["status"] == "running" and system["iteration"] == 2
    assert_merged_everywhere(main, Path(system["path"]))
    assert "plan v2" in _git(main, "show", "HEAD:docs/stories/OCX-91.md")  # the coordinator's file is committed

    await device_side.item_turn("flow-wiring")
    if run.context[device_work_state.GIT_KEY].get("sent"):
        await device_side.git_work(main_gateway)
    assert run.current_node_id == "pipeline"
    await device_side.prepares_main(main_gateway)  # the pipeline's job prepares the folder, then runs the tests
    merged.append(FILES["flow-wiring"])
    assert_merged_everywhere(main)
    assert _tracked(main) >= set(merged) and _git(main, "status", "--porcelain") == ""
    for name in merged:
        assert f"b/{name}" in run.context["device_change"]["patch"]  # the change the review and the push see


@_DEVICE_RUN
@pytest.mark.asyncio
async def test_an_items_stop_judges_only_its_own_proofs_when_items_share_a_role(db, tmp_path):
    """Units, store and render are all "backend" items. Units records done with its five proofs green; its Stop must
    not ask for the store and render proof tests ("Task list: no proof test in the change for store (...), render
    (...)"), else it blocks, the launcher stops anyway, the item fails "the item's turn ended without finishing it"
    and the run goes back to the plan."""
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.contract import run_contract
    from app.services.workflow_runs.octryx.facts import FACTS_KEY
    from app.services.workflow_runs.octryx.stop import run_stop

    admin, project, device, thread, run, main, base = await _story_run(db, tmp_path)
    plan = [_item("units", "backend", ["src/units/**"]), _item("store", "backend", ["src/store/**"])]
    await coordinator_plans(db, admin, project, thread, run, plan=plan)
    await Device(db, admin, project, run, main, base).git_work()
    units = _items(run)["units"]
    job = await db.get(DeviceJob, units["job_id"])
    gateway = await _gateway_session(db, admin, project.id, str(uuid.uuid4()))
    await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=project.id, run_id=run.id,
                              job_id=job.id)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    contract = await run_contract(db, run, session=gateway)
    assert [task["id"] for task in contract["phase"]["task_list"]] == ["units"]  # never the store item's

    recorded = await Device(db, admin, project, run, main, base).agent_submits(gateway, "units")
    assert recorded["state"] == "recorded"
    change = {"patch": "diff --git a/tests/test_units.py b/tests/test_units.py\n+++ b/tests/test_units.py\n"
                       "@@ -0,0 +1,2 @@\n+def test_it():\n+    assert True\n"}
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop", FACTS_KEY: {"change": change}},
                            tool_calls=[], test_prefixes=())
    assert answer["state"] == "passed", answer
    assert _items(run)["units"]["status"] in ("done", "merged")
