"""Server runners: enrollment with the join secret, pool turns with thread affinity, the Workspace switch."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import DeviceJob, Project, Session, User, UserDevice
from app.services.devices.hub import device_hub
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.runner_identity import runner_turn_owner
from app.services.devices.runner_pool import (
    RUNNER_ACCOUNT_TYPE,
    RUNNER_SERVICE_KIND,
    RUNNER_USERNAME,
    runners_online,
)
from app.services.workflow_runs.runtime_target.target import target_options
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    enable_device_runs,
    new_key_pair,
    oauth_client,
    user_named,
)

ENROLL = "/api/v1/devices/runner/enroll"


class Connected(RecordingConnection):
    seat_login = False


@pytest.fixture(autouse=True)
async def _runners_on(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_join_secret", "join-secret-for-tests")
    device_hub.clear()
    await enable_device_runs(db)
    yield
    device_hub.clear()


async def _enroll(client, db, name="runner-a", secret="join-secret-for-tests", runtime=""):
    await oauth_client(db)
    _private, public = new_key_pair()
    enrolled = await client.post(ENROLL, json={"join_secret": secret, "client_id": "octryx-test-client", "name": name,
                                               "public_key": public, "client_version": "0.0.2", "runtime": runtime})
    if enrolled.status_code == 201:  # what the runner's launcher reports at its handshake
        (await db.get(UserDevice, enrolled.json()["device"]["id"])).engines = ["claude_code", "codex"]
        await db.flush()
    return enrolled


@pytest.mark.asyncio
async def test_a_runner_enrolls_with_the_join_secret_as_a_platform_device(client, db):
    refused = await _enroll(client, db, secret="wrong")
    assert (refused.status_code, refused.json()["reason"]) == (403, "runner_join_secret_invalid")
    enrolled = await _enroll(client, db)
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.json()["credential"]["refresh_token"]
    device = await db.get(UserDevice, enrolled.json()["device"]["id"])
    owner = await db.get(User, device.owner_user_id)
    assert (owner.username, owner.account_type) == (RUNNER_USERNAME, RUNNER_ACCOUNT_TYPE)
    assert device.service_kind == RUNNER_SERVICE_KIND and device.folders == ["/workspace"]


@pytest.mark.asyncio
async def test_enrollment_without_a_configured_secret_is_off(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_join_secret", "")
    response = await _enroll(client, db)
    assert (response.status_code, response.json()["reason"]) == (503, "runner_enrollment_not_configured")


@pytest.mark.asyncio
async def test_with_a_required_runtime_no_runner_joins_on_another_and_the_pool_needs_configuration(
        client, db, auth_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "runner_runtime", "gvisor")
    refused = await _enroll(client, db, runtime="")
    assert (refused.status_code, refused.json()["reason"]) == (409, "runner_runtime_mismatch")
    assert (await db.execute(select(UserDevice))).scalars().all() == []
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    response = await _pool_send(client, auth_headers, project.id)
    assert (response.status_code, response.json()["detail"]["state"], response.json()["detail"]["reason"]) == (
        409, "needs_configuration", "runner_pool_not_set_up")  # never a turn on a plain runtime instead
    assert (await _enroll(client, db, name="runner-g", runtime="gvisor")).status_code == 201


@pytest.mark.asyncio
async def test_a_runner_enrolled_before_the_runtime_was_required_takes_no_turn(client, db, auth_headers, monkeypatch):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    monkeypatch.setattr(get_settings(), "runner_runtime", "gvisor")  # an upgrade whose new pods cannot start
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    pooled = await _pool_send(client, auth_headers, project.id)
    assert (pooled.status_code, pooled.json()["detail"]["reason"]) == (409, "runner_pool_not_set_up")
    body = {"prompt": "x", "project_id": project.id, "execution_target": {
        "kind": "device", "device_id": runner.id, "folder": "/workspace/abc", "profile": "governed"}}
    direct = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert direct.json()["detail"]["reason"] == "runner_runtime_mismatch"
    assert await runners_online(db) == 0  # the start dialog offers no pool either


async def _pool_send(client, headers, project_id, session_id=""):
    body = {"prompt": "Fix the add function", "project_id": project_id,
            "execution_target": {"kind": "device", "device_id": "pool", "profile": "governed"}}
    if session_id:
        body["session_id"] = session_id
    return await client.post("/chat/api/send", json=body, headers=headers)


@pytest.mark.asyncio
async def test_a_pool_turn_runs_on_a_free_runner_and_the_thread_stays_there(client, db, auth_headers, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    empty = await _pool_send(client, auth_headers, project.id)
    assert (empty.status_code, empty.json()["detail"]["reason"]) == (409, "runner_pool_not_set_up")
    assert empty.json()["detail"]["message"].startswith("No server runner is set up")

    first = await db.get(UserDevice, (await _enroll(client, db, "runner-a")).json()["device"]["id"])
    second = await db.get(UserDevice, (await _enroll(client, db, "runner-b")).json()["device"]["id"])
    for runner in (first, second):
        device_hub._connections[runner.id] = Connected(runner.id)
    response = await _pool_send(client, auth_headers, project.id)
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    session = await db.get(Session, job.session_id)
    target = session.metadata_["execution_target"]
    assert target["pool"] is True and target["device_id"] == job.device_id
    assert target["folder"].startswith("/workspace/") and session.user_id == auth_user.id
    connection = device_hub._connections[job.device_id]
    await DeviceJobHandlers().tick(db, connection)
    assert connection.sent[0][0] == "job_offer" and connection.sent[0][1]["folder"] == target["folder"]

    job.status, job.turn_state = "idle", "done"
    await db.flush()
    again = await _pool_send(client, auth_headers, project.id, session_id=session.id)
    assert again.status_code == 200, again.text
    jobs = (await db.execute(select(DeviceJob).where(DeviceJob.session_id == session.id))).scalars().all()
    assert {item.device_id for item in jobs} == {job.device_id}  # the thread's Codex thread lives on that runner


@pytest.mark.asyncio
async def test_a_runner_never_serves_two_people_or_workspaces_at_once(client, db, auth_headers):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    runner.max_parallel_jobs = 4
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    other = await user_named(db, "someone-else")
    busy = DeviceJob(device_id=runner.id, owner_user_id=other.id, session_id=(await chat_session(db, other)).id,
                     workspace_id=project.id, folder="/workspace/b0b", profile="governed", status="running")
    db.add(busy)
    await db.flush()
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200  # it waits for the runner
    queued = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id != other.id))).scalar_one()
    assert (queued.status, queued.device_id) == ("waiting_runner", None)
    body = {"prompt": "x", "project_id": project.id, "execution_target": {
        "kind": "device", "device_id": runner.id, "folder": "/workspace/abc", "profile": "governed"}}
    direct = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert direct.json()["detail"]["reason"] == "device_busy"  # the gate holds for a runner named by its id too
    connection = device_hub._connections[runner.id]
    await DeviceJobHandlers().tick(db, connection)
    assert (await db.get(DeviceJob, queued.id)).status == "waiting_runner"
    busy.status = "idle"
    await db.flush()
    await DeviceJobHandlers().tick(db, connection)
    await db.refresh(queued)
    assert (queued.status, queued.device_id) == ("offered", runner.id)
    assert connection.sent[-1][1]["owner_user_id"] == queued.owner_user_id  # the launcher empties itself on a switch


@pytest.mark.asyncio
async def test_a_workspace_can_switch_server_runners_off(client, db, auth_headers):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project.config = {**(project.config or {}), "server_runners": "forbidden"}
    await db.flush()
    response = await _pool_send(client, auth_headers, project.id)
    assert (response.status_code, response.json()["detail"]["reason"]) == (403, "server_runners_forbidden")


@pytest.mark.asyncio
async def test_nobody_targets_a_runner_by_its_id_outside_the_pools_rules(client, db, auth_headers):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    project.config = {**(project.config or {}), "server_runners": "forbidden"}
    await db.flush()
    body = {"prompt": "x", "project_id": project.id, "execution_target": {
        "kind": "device", "device_id": runner.id, "folder": "/workspace/abc", "profile": "governed"}}
    response = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert response.json()["detail"]["reason"] == "device_target_not_owner"


@pytest.mark.asyncio
async def test_a_runners_calls_act_for_the_turns_owner_only_while_the_turn_is_active(client, db, auth_headers, auth_user):
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    account = await db.get(User, runner.owner_user_id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    acting = {"grant_id": runner.grant_id, "workspace_id": project.id}
    assert await runner_turn_owner(db, account, **acting) is None  # no turn: a member of nothing
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    assert (await runner_turn_owner(db, account, **acting)).id == auth_user.id
    assert await runner_turn_owner(db, auth_user, **acting) is None  # only the runner account is ever mapped
    assert await runner_turn_owner(db, account, grant_id="other-grant", workspace_id=project.id) is None
    job = (await db.execute(select(DeviceJob))).scalar_one()
    job.status = "idle"
    await db.flush()
    assert await runner_turn_owner(db, account, **acting) is None


@pytest.mark.asyncio
async def test_the_start_dialog_offers_the_pool_while_a_runner_is_online(client, db, auth_user):
    assert not [option for option in await target_options(db, user=auth_user) if option["target"].get("pool")]
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    pool = [option for option in await target_options(db, user=auth_user) if option["target"].get("pool")]
    assert [option["target"]["profile"] for option in pool] == ["governed"]


@pytest.mark.asyncio
async def test_a_turn_in_a_private_workspace_reaches_the_runner_and_keeps_it_from_a_second_person(
        client, db, auth_headers, auth_user):
    from app.services.data_access import as_viewer
    from app.services.devices.channel import DeviceChannelSession
    from app.services.devices.runner_pool import serves_someone_else
    from app.services.devices.runner_tenant import runner_channel_viewer
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import FakeSocket, SharedSession

    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    connection = Connected(runner.id)
    device_hub._connections[runner.id] = connection
    private = await ensure_private_workspace(db, auth_user)
    config = dict(private.config or {})
    config["agent_gateway_policy"] = {**dict(config.get("agent_gateway_policy") or {}),
                                      "device_runs": {"enabled": True}}
    private.config = config
    await db.commit()
    assert (await _pool_send(client, auth_headers, private.id)).status_code == 200
    account = await db.get(User, runner.owner_user_id)

    with as_viewer(account.id):
        # The runner account itself sees nothing of the private Workspace.
        assert (await db.execute(select(DeviceJob).where(DeviceJob.device_id == runner.id))).first() is None
        assert await runner_channel_viewer(db, runner.id) == auth_user.id
        channel = DeviceChannelSession(FakeSocket(), token="", session_factory=SharedSession(db))
        channel._runner = True
        async with channel._for_turns(db, runner.id):
            await DeviceJobHandlers().tick(db, connection)
        owner = await runner_turn_owner(db, account, grant_id=runner.grant_id, workspace_id=private.id)
    assert [kind for kind, _body in connection.sent if kind == "job_offer"], "the private turn is offered"
    assert owner is not None and owner.id == auth_user.id

    other = await user_named(db, "second-person")
    acme = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    with as_viewer(other.id):  # the other person cannot see the private turn, and the runner is still busy
        assert await serves_someone_else(db, runner, owner_user_id=other.id, workspace_id=acme.id)

async def test_a_runners_mcp_calls_act_for_the_turns_owner_and_its_writes_wait_for_approval(
        client, db, auth_headers, auth_user, monkeypatch):
    import json

    from app.services.devices.contract import DEVICE_JOB_SCOPES
    from app.services.oauth_provider.tokens import mint_access_token
    from tests.mcp_claude_code_parity_support import _native
    from tests.mcp_native_support import mcp_request

    _native(db, monkeypatch)
    runner = await db.get(UserDevice, (await _enroll(client, db)).json()["device"]["id"])
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token, _ = mint_access_token(user_id=runner.owner_user_id, client_id="octryx-test-client", grant_id=runner.grant_id,
                                 scopes=sorted(DEVICE_JOB_SCOPES), resource=None)
    headers = {"X-Octryx-Workspace": project.id}

    async def call(name, arguments):
        result = (await mcp_request(token, "tools/call", {"name": name, "arguments": arguments}, headers))["result"]
        return json.loads(result["content"][0]["text"])

    # No active turn: the runner account is a member of nothing.
    assert (await call("tool_call", {"name": "product_run_list"}))["state"] == "not_found"
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    await db.commit()
    assert "workflow_runs" in await call("tool_call", {"name": "product_run_list"}), "acts for the turn's owner"
    write = {"name": "knowledge_episode_summary", "arguments": {"summary": "x"}}
    held = await call("tool_call", write)
    assert held["approval_required"] is True and held["approval_id"], held
    from app.services.approval.resolution_service import resolve_approval_request

    await resolve_approval_request(db, approval_id=held["approval_id"], resolved_by=auth_user.id, status="approved")
    await db.commit()
    assert "approval_required" not in await call("tool_call", write), "the approved write runs"
    project.config = {**(project.config or {}), "tool_policy": {"denylist": ["product_run_list"]}}
    await db.commit()
    assert (await call("tool_call", {"name": "product_run_list"}))["reason"] == "tool_not_offered"
