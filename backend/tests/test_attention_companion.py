"""The companion's queue (``GET /api/v1/attention``) and its live nudges."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import update

from app.models import ClarificationQuestion, DeviceJobApproval, User, WorkflowRun
from app.services.attention.stream import nudge_after_commit, user_stream_manager
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.limits import pause_run
from app.time_utils import utc_now
from tests.policy_engine_support import bearer
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import _device_run

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture(autouse=True)
def _clean():
    device_hub.clear()
    user_stream_manager.clear()
    yield
    device_hub.clear()
    user_stream_manager.clear()


def _by_kind(body: dict, kind: str) -> list[dict]:
    return [item for item in body["items"] if item["kind"] == kind]


@pytest.mark.asyncio
async def test_the_queue_lists_gates_problems_questions_device_approvals_and_finished_runs(client, db):
    admin, _device, thread, run = await _device_run(db)
    gate_hash = run.node_state["waiting"]["payload_hash"]
    db.add(ClarificationQuestion(session_id=thread.id, project_id=thread.project_id, question_id="q1",
                                 question_text="Which branch?", context_json={"options": ["main", "develop"]},
                                 requested_by=admin.id, status="open"))
    _admin2, _device2, thread2, run2 = await _device_run(db)
    await pause_run(db, run2, reason="runtime_failed", actor_id=None, detail={
        "message": "The device turn of this phase ended without finishing it (device_turn_error).",
        "code": "device_turn_error", "resume": {"kind": "restart", "node_id": "go"}})
    done = WorkflowRun(project_id=run.project_id, workflow_kind="phased", workflow_key="x", title="Done run",
                       requested_by=admin.id, status="completed", outcome="delivered", completed_at=utc_now(),
                       pull_request={"url": "https://bitbucket.org/team/repo/pull-requests/7"})
    db.add(done)
    await db.commit()

    body = (await client.get("/api/v1/attention", headers=bearer(admin.id))).json()
    [gate] = [item for item in _by_kind(body, "gate") if item["id"] == run.id]
    confirm = next(action for action in gate["actions"] if action["key"] == "confirm")
    assert confirm["request"] == {"method": "POST", "path": f"/api/v1/workflow-runs/{run.id}/actions",
                                  "body": {"action": "confirm", "payload_hash": gate_hash}}
    assert gate["session_id"] == thread.id and gate["severity"] == "action"

    [problem] = [item for item in _by_kind(body, "problem") if item["id"] == run2.id]
    assert problem["text"].startswith("The device turn of this phase") and problem["code"] == "device_turn_error"
    keys = {action["key"]: action for action in problem["actions"]}
    assert keys["continue"]["request"]["body"] == {"action": "continue", "k": 1}
    assert keys["abort"]["input"]["field"] == "reason" and keys["abort"]["tone"] == "danger"

    [question] = _by_kind(body, "question")
    assert [a["request"]["body"] for a in question["actions"][:2]] == [{"answer_text": "main"},
                                                                       {"answer_text": "develop"}]
    assert question["actions"][2]["input"]["field"] == "answer_text"

    [finished] = [item for item in _by_kind(body, "done") if item["id"] == done.id]
    assert finished["link"]["href"].endswith("/pull-requests/7")
    dismiss = finished["actions"][0]["request"]
    assert (await client.post(dismiss["path"], json=dismiss["body"], headers=bearer(admin.id))).status_code == 200
    again = (await client.get("/api/v1/attention", headers=bearer(admin.id))).json()
    assert not [item for item in _by_kind(again, "done") if item["id"] == done.id]

    states = {item["id"]: item["state"] for item in body["running"]}
    assert states[run.id] == "needs_you" and states[run2.id] == "problem" and states[done.id] == "done"
    assert thread2.id


@pytest.mark.asyncio
async def test_a_device_approval_offers_the_owners_decisions_with_its_expiry(client, db):
    from tests.workflow_run_octryx_continuation_support import _confirm, _jobs

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "approval_request", {
        "turn_id": job.turn_id, "approval_id": "ap1", "tool": "Edit", "input_preview": "/home/sample/src/t.py",
        "expires_at": time.time() + 300}, limits={"approval_timeout_s": 300})
    await db.commit()
    body = (await client.get("/api/v1/attention", headers=bearer(admin.id))).json()
    [entry] = _by_kind(body, "device_approval")
    approval = await db.get(DeviceJobApproval, entry["id"])
    path = f"/api/v1/device-jobs/{job.id}/approvals/{approval.id}"
    assert [(a["key"], a["request"]["path"], a["request"]["body"]) for a in entry["actions"]] == [
        ("allow_once", path, {"decision": "allow_once"}),
        ("allow_job_edits", path, {"decision": "allow_job_edits"}),
        ("deny", path, {"decision": "deny"})]
    assert entry["expires_at"]
    await db.execute(update(DeviceJobApproval).values(status="expired"))


@pytest.mark.asyncio
async def test_only_finished_entries_can_be_dismissed(client, auth_user: User):
    refused = await client.post("/api/v1/attention/dismiss", json={"key": "run:abc"}, headers=bearer(auth_user.id))
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_the_socket_needs_the_cookie_and_an_allowed_origin(db, auth_user: User):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.main import app
    from app.services.auth import create_access_token

    http = TestClient(app)  # no lifespan: only the socket's own checks run
    with pytest.raises(WebSocketDisconnect):
        with http.websocket_connect("/api/v1/attention/ws") as ws:
            ws.receive_json()
    http.cookies.set("access_token", create_access_token(auth_user.id))
    with pytest.raises(WebSocketDisconnect):
        with http.websocket_connect("/api/v1/attention/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()
    with http.websocket_connect("/api/v1/attention/ws") as ws:
        assert ws.receive_json() == {"type": "connected"}


@pytest.mark.asyncio
async def test_a_run_event_nudges_the_requesters_socket_only_after_the_commit(db):
    import asyncio

    from app.services.workflow_runs.records import record_event

    class Socket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def accept(self) -> None:
            return None

        async def send_json(self, data: dict) -> None:
            self.sent.append(data)

    admin, _device, _thread, run = await _device_run(db)
    socket = Socket()
    await user_stream_manager.connect(admin.id, socket)
    record_event(db, run, "reminder", node_id="go")
    await asyncio.sleep(0)
    assert socket.sent == [{"type": "connected"}]  # nothing before the commit
    await db.commit()
    await asyncio.sleep(0.05)
    assert {"type": "attention_changed", "run_id": run.id, "event": "reminder"} in socket.sent
    assert nudge_after_commit(db, None) is None


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


@pytest.mark.asyncio
async def test_tool_and_phase_events_reach_only_the_runs_watchers_a_waiting_event_nudges_once(db):
    import asyncio

    from app.services.workflow_runs.records import record_event

    admin, _device, _thread, run = await _device_run(db)
    await db.commit()  # the start's own nudges go out before anyone listens
    await asyncio.sleep(0.05)
    companion, watcher = _Socket(), _Socket()
    await user_stream_manager.connect(admin.id, companion)
    await user_stream_manager.watch(run.id, watcher)
    for kind in ("tool_allowed_by_default", "session_bound", "wip_pushed", "phase_turn", "node_entered"):
        record_event(db, run, kind, node_id="go")
    await db.commit()
    await asyncio.sleep(0.05)
    assert [m for m in companion.sent if m["type"] == "attention_changed"] == []
    assert {"type": "job_changed", "run_id": run.id} in watcher.sent

    record_event(db, run, "waiting", node_id="go")
    await db.commit()
    await asyncio.sleep(0.05)
    assert [m for m in companion.sent if m["type"] == "attention_changed"] == [
        {"type": "attention_changed", "run_id": run.id, "event": "waiting"}]


def test_every_nudging_event_kind_is_one_the_platform_records():
    import re
    from pathlib import Path

    from app.services.attention.stream import NUDGE_EVENT_KINDS

    backend = Path(__file__).resolve().parents[1] / "app"
    literals = {m for path in backend.rglob("*.py") for m in re.findall(r'"([a-z_]+)"', path.read_text("utf-8"))}
    assert NUDGE_EVENT_KINDS <= literals
