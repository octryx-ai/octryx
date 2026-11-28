"""The device, repository, story run and coordinator plan set-up shared by the team delivery rehearsal tests."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.models import DeviceJob
from app.models.runtime.secure_work import WorkItem
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.devices.job_state import ACTIVE_STATUSES
from app.services.mcp_governed_knowledge import McpCaller
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.teamwork import WORK_KEY, device_work_state, work_git
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.teamwork_device_support import _gateway_session  # noqa: F401 - fixtures
from tests.test_team_delivery import _seed, actions  # noqa: F401 - ``actions`` is a fixture

CLIENT_DIR = Path(__file__).resolve().parents[2] / "clients" / "octryx-claude"


BRANCH = "feature/OCX-91-search"


_DEVICE_RUN = pytest.mark.usefixtures("actions")


@pytest.fixture
def agent_checks_pass(monkeypatch):
    from app.services.workflow_runs.octryx import stop as stop_module

    monkeypatch.setattr(stop_module, "evaluate_checks", lambda checks, evidence: [])


def _launcher():
    if str(CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(CLIENT_DIR))
    from octryx_claude import work_git, workspace_prep

    return work_git, workspace_prep


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    main = tmp_path / "kitchen-helper"
    main.mkdir()
    _git(main, "init", "-q", "-b", BRANCH)
    (main / ".gitignore").write_text(".venv/\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "start")
    return main, _git(main, "rev-parse", "HEAD")


def _item(key: str, role: str, paths: list[str], depends_on=None) -> dict:
    return {"id": key, "title": f"Build {key}", "role": role, "depends_on": depends_on or [],
            "paths": [*paths, f"tests/test_{key.replace('-', '_')}.py"],
            "instructions": f"Build {key}.", "proofs": [f"tests/test_{key.replace('-', '_')}.py::test_it"]}


PLAN = [_item("core-domain", "backend", ["src/core/**"]),
        _item("frontend-shell", "frontend", ["web/shell/**"]),
        _item("frontend-components", "frontend", ["web/components/**"]),
        # The dependent item wires the screens to the domain (a test item never waits: it writes its tests from the
        # contract while the others build, ``plan.starts_at_once``).
        _item("flow-wiring", "frontend", ["web/flow/**"], depends_on=["core-domain", "frontend-shell"])]


FILES = {"core-domain": "src/core/corpus.py", "frontend-shell": "web/shell/app.js",
         "frontend-components": "web/components/button.js", "flow-wiring": "web/flow/wiring.js"}


class Device:
    def __init__(self, db, admin, project, run, main: Path, base: str):
        self.db, self.admin, self.project, self.run, self.main, self.base = db, admin, project, run, main, base
        self.work_git, self.prep = _launcher()

    async def job(self, job_id: str) -> DeviceJob:
        return await self.db.get(DeviceJob, job_id)

    async def prepares_main(self, gateway) -> dict:
        from app.services.workflow_runs.octryx.contract import run_contract

        contract = await run_contract(self.db, self.run, session=gateway)
        report = self.prep.prepare(contract, self.main, runtime="device")
        assert report["branch"]["state"] in ("already", "checked_out"), report
        return report

    async def git_work(self, main_gateway=None) -> None:
        if main_gateway is not None:
            await self.prepares_main(main_gateway)
        state = self.run.context[device_work_state.GIT_KEY]
        job = await self.job(state["sent"]["job_id"])
        view = work_git.contract_view(self.run)
        report = self.work_git.run(view, self.main, base=self.base, run_id=self.run.id)
        assert await work_git.work_git_reported(self.db, self.run, report) == "recorded"
        await apply_event(self.db, job, "job_rejected", {"turn_id": job.turn_id, "reason": "work_git_done"},
                          limits={})

    async def item_turn(self, key: str, value: str = "done") -> None:
        from app.services.workflow_runs.octryx.attach import bind_device_session
        from app.services.workflow_runs.octryx.contract import run_contract
        from app.services.workflow_runs.octryx.stop import run_stop
        from app.services.workflow_runs.workspace.gateway import report_preparation

        item = self.run.context[WORK_KEY]["items"][key]
        job = await self.job(item["job_id"])
        gateway = await _gateway_session(self.db, self.admin, self.project.id, str(uuid.uuid4()))
        assert await bind_device_session(self.db, gateway_session=gateway, user=self.admin,
                                         workspace_id=self.project.id, run_id=self.run.id, job_id=job.id)
        contract = await run_contract(self.db, self.run, session=gateway)
        assert contract["phase"]["work_item"]["id"] == key
        assert contract["preparation"]["branch"] == f"{BRANCH}--{key}"
        folder = Path(item["path"])
        report = self.prep.prepare(contract, folder, runtime="device")
        assert (await report_preparation(self.db, session=gateway, payload=report))["state"] == "ready"
        await apply_event(self.db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
        target = folder / FILES[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {key}\n")
        recorded = await self.agent_submits(gateway, key, value)
        assert recorded["state"] == "recorded" and recorded["item"] == key, recorded
        answer = await run_stop(self.db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                                test_prefixes=())
        assert answer["state"] == "passed", answer
        await apply_event(self.db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                          "result_text": f"{key} done"}, limits={})


    def caller(self, gateway) -> McpCaller:
        from app.services.agent_gateway.contract import SESSION_KEY_METADATA

        return McpCaller(user_id=self.admin.id, grant_id="mcp", scopes=("workflow:read", "workflow:execute"),
                         workspace_header=self.project.id, session_key=gateway.metadata_[SESSION_KEY_METADATA],
                         transport="mcp")

    async def agent_submits(self, gateway, key: str, value: str = "done") -> dict:
        from app.services.agent_gateway.policy import load_workspace_policy
        from app.services.mcp_workflow_run_tools import PHASE_OUTPUT_MCP_HANDLERS, mcp_workflow_run_status
        from app.services.workflow_runs.octryx.hooks import run_pre_tool_use

        caller = self.caller(gateway)
        status = await mcp_workflow_run_status(self.db, caller=caller, user=self.admin, workspace_id=self.project.id,
                                               arguments={})
        phase = status["workflow_run"]["phase"]
        assert phase is not None and phase["work_item"]["id"] == key, status["workflow_run"]
        assert "submit_phase_result" in phase["tools"]["allow"]
        policy = (await load_workspace_policy(self.db, self.project.id)).policy
        decision, _contract = await run_pre_tool_use(self.db, session=gateway, policy=policy, hook_input={
            "hook_event_name": "PreToolUse", "tool_name": "mcp__octryx-knowledge__submit_phase_result",
            "tool_input": {"value": value}, "cwd": str(Path(self.run.context[WORK_KEY]["items"][key]["path"]))})
        assert decision is None or decision.decision != "deny", decision
        return await PHASE_OUTPUT_MCP_HANDLERS["submit_phase_result"](
            self.db, caller=caller, user=self.admin, workspace_id=self.project.id,
            arguments={"value": value, "summary": f"{key} built"})


async def _story_run(db, tmp_path, *, slots: int = 4):
    main, base = _repository(tmp_path)
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin, folders=[str(main)])
    device.client_version, device.max_parallel_jobs = "0.0.1a0+abc", slots
    device_hub._connections[device.id] = RecordingConnection(device.id)
    thread = await new_chat_session(db, admin, project.id)
    thread.metadata_ = {**dict(thread.metadata_ or {}), "execution_target": {
        "kind": "device", "device_id": device.id, "folder": str(main), "profile": "governed", "model": ""}}
    story = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-91", title="Search",
                     epic_key="OCX-90", project_id=project.id, work_state="intake")
    db.add(story)
    await db.flush()
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _seed()["definition"]),
                          project_id=project.id, work_item_id=story.id, session=thread)
    run.branch = BRANCH
    from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY

    run.context = {**run.context, "base_sha": base, CONTEXT_KEY: {
        "state": "ready", "runtime": "device", "node_id": "prepare", "entry": 2,
        "spec": {"branch": BRANCH, "head": base, "repository": None, "environment": None}}}
    assert run.current_node_id == "plan"
    return admin, project, device, thread, run, main, base


async def _thread_job(db, session_id):
    from app.services.devices.jobs import thread_job

    return await thread_job(db, session_id)


async def coordinator_plans(db, admin, project, thread, run, plan=PLAN):
    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.stop import run_stop
    from app.services.workflow_runs.phase_outputs import submit_output

    job = await _thread_job(db, thread.id)
    assert job is not None and job.status in ACTIVE_STATUSES
    gateway = await _gateway_session(db, admin, project.id, str(uuid.uuid4()))
    assert await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=project.id,
                                     run_id=run.id, job_id=job.id)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    recorded = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/search", "items": plan},
                                   session_id=gateway.id)
    assert recorded["state"] == "recorded", recorded
    answer = await run_stop(db, session=gateway, hook_input={"hook_event_name": "Stop"}, tool_calls=[],
                            test_prefixes=())
    assert answer["state"] == "passed", answer
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                 "result_text": "Planned."}, limits={})
    return gateway


def _items(run) -> dict:
    return run.context[WORK_KEY]["items"]
