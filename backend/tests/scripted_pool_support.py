"""A server run's phase turns on the pool, scripted: one in-process runner accepts each turn as an offered job; a test
plays the job's end through ``finish_turn``."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, UserDevice
from app.services.devices.chat_turn import DeviceTurnStarted
from app.services.workflow_runs.octryx import continuation
from app.services.workflow_runs.runtime_target import target as target_module

RUNNER_ID = "runner-scripted"
POOL_FOLDER = "/workspace/run"


@pytest.fixture
def scripted_pool(monkeypatch) -> list[DeviceJob]:
    from app.services.devices.hub import device_hub
    from tests.devices.device_support import RecordingConnection

    offered: list[DeviceJob] = []
    # Connected like a live runner: the silence sweep never takes it for offline.
    monkeypatch.setitem(device_hub._connections, RUNNER_ID, RecordingConnection(RUNNER_ID))

    real_validate = target_module.validate_target
    scripted_target = {"kind": "device", "device_id": RUNNER_ID, "folder": POOL_FOLDER, "pool": True,
                       "profile": "governed", "model": "team-coder"}

    async def on_pool(db, *, user, project_id, provenance):
        await _runner_device(db, user.id)
        # Like the pool: a fresh folder on the runner for each run.
        return {**scripted_target, "folder": f"{POOL_FOLDER}-{uuid.uuid4().hex[:8]}", **provenance}

    async def validate(db, *, user, project_id, raw, repository=None):
        parsed = target_module.parse_target(raw)
        if parsed is not None and parsed.get("device_id") == RUNNER_ID:
            return {**scripted_target, "folder": parsed.get("folder") or POOL_FOLDER}
        return await real_validate(db, user=user, project_id=project_id, raw=raw, repository=repository)

    real_start = continuation._start_continuation_turn

    async def start_turn(db, run, marker, node, turn_node, thread, target, suffix):
        if target.get("device_id") != RUNNER_ID:  # a real device's turn takes the real path
            return await real_start(db, run, marker, node, turn_node, thread, target, suffix)
        await _runner_device(db, thread.user_id)
        job = DeviceJob(device_id=RUNNER_ID, owner_user_id=thread.user_id, session_id=thread.id,
                        workspace_id=thread.project_id, folder=POOL_FOLDER, profile="governed", status="offered",
                        turn_count=1, turn_prompt=f"{run.id}:{turn_node.id}{suffix}", turn_state="pending",
                        turn_id=uuid.uuid4().hex)
        db.add(job)
        await db.flush()
        offered.append(job)
        return DeviceTurnStarted(session=thread, job_id=job.id)

    from app.services.workflow_runs.workspace import preparation

    real_prepare = preparation.prepare_workspace

    async def prepare(db, run, node):
        # The scripted runner's folder is ready at once, as the server's copy was (a real device takes the real path).
        from app.services.workflow_runs.graph import SUCCEEDED
        from app.services.workflow_runs.platform.dispatch import ToolOutcome
        from app.services.workflow_runs.runtime_target.target import stored_target
        from app.time_utils import utc_now as _now

        on_runner = await preparation.runtime_of(db, run) == preparation.RUNTIME_DEVICE
        if not on_runner or (stored_target(run) or {}).get("device_id") != RUNNER_ID or not run.branch:
            return await real_prepare(db, run, node)
        spec = await preparation.requirement(db, run)
        preparation._set(run, {"state": preparation.STATE_READY, "runtime": preparation.RUNTIME_DEVICE,
                               "node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "spec": spec,
                               "report": {"runtime": "device", "branch": {"state": "already"}},
                               "at": _now().isoformat()})
        return ToolOutcome(SUCCEEDED, {"runtime": "device"}), SUCCEEDED

    monkeypatch.setattr(preparation, "prepare_workspace", prepare)
    from app.services.workflow_runs.handoff import permissions
    from app.services.workflow_runs.runtime_target import switch

    monkeypatch.setattr(target_module, "_on_pool", on_pool)
    for module in (target_module, permissions, switch):
        monkeypatch.setattr(module, "validate_target", validate)
    monkeypatch.setattr(continuation, "_start_continuation_turn", start_turn)
    return offered


@pytest.fixture
def scripted_turns(monkeypatch) -> dict:
    # Every awaited runner turn (run_pool_turn) answers from the script: ``answers`` in order, else ``default``.
    from app.models import Message, Session
    from app.services.devices import agent_runtime

    state: dict = {"answers": [], "default": "done", "calls": []}

    async def run_pool_turn(db, *, user_id, prompt, session_id="", project_id="", timeout=0.0, target=None,
                            rerun_message=None):
        session = await db.get(Session, session_id) if session_id else None
        if session is None:
            session = Session(user_id=user_id, project_id=project_id or None, status="active", origin="device_chat",
                              metadata_={})
            db.add(session)
            await db.flush()
        asked = rerun_message or Message(session_id=session.id, role="user", content=prompt)
        db.add(asked)
        script = state["answers"].pop(0) if state["answers"] else state["default"]
        answer = await script(prompt) if callable(script) else str(script)
        db.add(Message(session_id=session.id, role="assistant", content=answer))
        await db.flush()
        state["calls"].append({"user_id": user_id, "prompt": prompt, "session_id": session.id, "target": target,
                               "project_id": project_id or session.project_id})
        return agent_runtime.PoolTurn(session.id, f"dj_scripted_{len(state['calls'])}", asked.id, "done", answer)

    monkeypatch.setattr(agent_runtime, "run_pool_turn", run_pool_turn)
    return state


async def _runner_device(db, _owner_id: str) -> None:
    from app.services.devices.runner_pool import RUNNER_SERVICE_KIND, runner_account

    if await db.get(UserDevice, RUNNER_ID) is None:
        # Like an enrolled runner: the runner account's device, never the person's.
        account = await runner_account(db, create=True)
        db.add(UserDevice(id=RUNNER_ID, owner_user_id=account.id, name="scripted runner", name_key="scripted runner",
                          os="linux", public_key="scripted", folders=[POOL_FOLDER], profiles=["governed"],
                          service_kind=RUNNER_SERVICE_KIND))
        await db.flush()


async def finish_turn(db, job: DeviceJob, *, said: str = "", failure: str | None = None) -> None:
    from app.services.workflow_runs.octryx.continuation import continue_after_device_turn

    job.status = "failed" if failure else "completed"
    await db.flush()
    await continue_after_device_turn(db, job.session_id, failure=failure, said=said)


async def last_offered(db) -> DeviceJob | None:
    return (await db.execute(select(DeviceJob).order_by(DeviceJob.created_at.desc()).limit(1))).scalar_one_or_none()


__all__ = ["POOL_FOLDER", "RUNNER_ID", "finish_turn", "last_offered", "scripted_pool", "scripted_turns"]
