"""The model of a device job: the rows per profile (octryx-claude's ``/model``), the coded
refusal of a model outside them, the model in the offer, and the model the device reports."""

from __future__ import annotations

import types

import pytest
from sqlalchemy import func, select

from app.models import DeviceJob, Project
from app.services.agent_gateway.seat_policy import SeatDecision
from app.services.devices import device_models
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.devices.job_state import serialize_job
from app.services.devices.jobs_channel import DeviceJobHandlers
from tests.devices.device_support import RecordingConnection, chat_session, device_with_grant, enable_device_runs

FOLDER = "/home/sample/src"
COMPANY = (types.SimpleNamespace(alias="co-sonnet", display_name="Company Sonnet"),)


@pytest.fixture(autouse=True)
async def _device_runs_on(db, monkeypatch):
    device_hub.clear()
    await enable_device_runs(db)

    async def admitted(_db, _workspace_id):
        return COMPANY

    monkeypatch.setattr(device_models, "admitted_tool_aliases", admitted)
    yield
    device_hub.clear()


def _seat(monkeypatch, decision: SeatDecision) -> None:
    async def seat(_db, _workspace_id, *, principal=None):
        return decision

    monkeypatch.setattr(device_models, "workspace_seat_decision", seat)


async def _project(db):
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()


@pytest.mark.asyncio
async def test_rows_follow_the_profile_and_the_seat_policy(db, auth_user, monkeypatch):
    project = await _project(db)

    async def ids(profile):
        options = await device_models.device_model_options(db, user_id=auth_user.id, workspace_id=project.id,
                                                           profile=profile)
        return [model.id for model in options.models], options.reason

    assert await ids("governed") == (["co-sonnet"], "")
    _seat(monkeypatch, SeatDecision(True, models=("claude-sonnet-5",)))
    assert await ids("seat") == (["claude-sonnet-5"], "")
    _seat(monkeypatch, SeatDecision(True, models=("claude-sonnet-5",), governed_models=True))
    assert await ids("seat") == (["claude-sonnet-5", "company/co-sonnet"], "")
    _seat(monkeypatch, SeatDecision(False, "seat_mode_forbidden"))
    assert await ids("seat") == ([], "seat_mode_forbidden")


@pytest.mark.asyncio
async def test_subscription_rows_carry_the_catalog_name_never_the_bare_id(db, auth_user, monkeypatch):
    """The device Model pill must not show ``Model: claude-opus-5-5``. A catalog row named after the bare id
    repeats the id; the provider-prefixed row names it."""
    import uuid

    from app.models import LLMModel, LLMProvider

    provider = LLMProvider(id=str(uuid.uuid4()), name="anthropic-c2", display_name="Anthropic", is_global=True,
                           is_active=True)
    db.add(provider)
    await db.flush()
    db.add_all([
        LLMModel(provider_id=provider.id, model_id="claude-opus-5-5", display_name="claude-opus-5-5"),
        LLMModel(provider_id=provider.id, model_id="anthropic.claude-opus-5-5", display_name="Claude Opus 5.5",
                 is_active=False),
    ])
    await db.flush()
    project = await _project(db)
    _seat(monkeypatch, SeatDecision(True, models=("claude-opus-5-5", "claude-sonnet-5", "x/odd id")))

    options = await device_models.device_model_options(db, user_id=auth_user.id, workspace_id=project.id,
                                                       profile="seat")

    assert [(model.id, model.display_name) for model in options.models] == [
        ("claude-opus-5-5", "Claude Opus 5.5"), ("claude-sonnet-5", "Claude Sonnet 5"), ("x/odd id", "x/odd id")]


def test_a_model_id_without_a_catalog_name_reads_as_a_name():
    assert device_models.readable_model_name("claude-haiku-4-5-20251001") == "Claude Haiku 4.5"
    assert device_models.readable_model_name("claude-sonnet-5-5") == "Claude Sonnet 5.5"
    assert device_models.readable_model_name("company/co-sonnet") == "company/co-sonnet"


@pytest.mark.asyncio
async def test_picker_route_is_for_members_and_own_devices(client, db, auth_headers, auth_user):
    project = await _project(db)
    device, _ = await device_with_grant(db, auth_user)
    path = f"/api/v1/workspaces/{project.id}/agent-gateway/device-runs/models"
    response = await client.get(path, params={"profile": "governed", "device_id": device.id}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["models"]] == ["co-sonnet"]
    assert response.json()["models"][0]["source"] == "company"
    bad = await client.get(path, params={"profile": "root"}, headers=auth_headers)
    assert bad.status_code == 400
    foreign = await client.get(path, params={"profile": "governed", "device_id": "dev_missing"}, headers=auth_headers)
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_a_chosen_model_is_checked_offered_and_reported(client, db, auth_headers, auth_user):
    device, _ = await device_with_grant(db, auth_user)
    connection = RecordingConnection(device.id)
    device_hub._connections[device.id] = connection
    session = await chat_session(db, auth_user)

    def send(model):
        return client.post("/chat/api/send", headers=auth_headers, json={
            "prompt": "Run the tests", "session_id": session.id,
            "execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed",
                                 "model": model}})

    # A model outside the list becomes the nearest listed one, unless the Workspace keeps the list.
    from app.models import Project

    project = await db.get(Project, session.project_id)
    config = dict(project.config or {})
    gateway = dict(config.get("agent_gateway_policy") or {})
    gateway["device_runs"] = {**dict(gateway.get("device_runs") or {}), "tool_defaults": {"device_models": "list_only"}}
    project.config = {**config, "agent_gateway_policy": gateway}
    await db.commit()
    refused = await send("claude-not-offered")
    project.config = config
    await db.commit()
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason"] == "device_model_not_allowed"
    assert "not available" in refused.json()["detail"]["message"]
    assert (await db.execute(select(func.count()).select_from(DeviceJob))).scalar_one() == 0

    assert (await send("co-sonnet")).status_code == 200
    job = (await db.execute(select(DeviceJob))).scalar_one()
    await db.refresh(session)
    assert session.metadata_["execution_target"]["model"] == "co-sonnet"
    await DeviceJobHandlers().tick(db, connection)
    assert connection.sent[0][1]["model"] == "co-sonnet"
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "cs-1", "model": "co-sonnet"},
                      limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert serialize_job(job)["model"] == "co-sonnet" and serialize_job(job)["requested_model"] == "co-sonnet"

    # The device default on the next turn: the same job and Claude Code session, the model reported anew.
    assert (await send("")).status_code == 200
    await db.refresh(job)
    assert (await db.execute(select(func.count()).select_from(DeviceJob))).scalar_one() == 1
    assert job.turn_model is None and job.model is None and job.turn_count == 2
    await DeviceJobHandlers().tick(db, connection)
    assert connection.sent[-1][1]["model"] == "" and connection.sent[-1][1]["resume_session_id"] == "cs-1"



@pytest.mark.asyncio
async def test_the_chats_permission_mode_and_effort_reach_the_offer(client, db, auth_headers, auth_user):
    # A chat on the Mac works like Claude Code: mode (bypass included) and effort per turn; bypass
    # for the Workspace's owners only (the admin owns the test Workspace by membership).
    device, _ = await device_with_grant(db, auth_user)
    connection = RecordingConnection(device.id)
    device_hub._connections[device.id] = connection
    session = await chat_session(db, auth_user)

    def send(**target):
        return client.post("/chat/api/send", headers=auth_headers, json={
            "prompt": "Fix the test", "session_id": session.id,
            "execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed",
                                 **target}})

    assert (await send(permission_mode="yolo")).status_code == 422
    assert (await send(permission_mode="bypassPermissions", effort="high")).status_code == 200
    await DeviceJobHandlers().tick(db, connection)
    offer = connection.sent[-1][1]
    assert (offer["permission_mode"], offer["effort"]) == ("bypassPermissions", "high")
    await db.refresh(session)
    assert session.metadata_["execution_target"]["permission_mode"] == "bypassPermissions"


@pytest.mark.asyncio
async def test_bypass_off_in_the_workspace_refuses_a_bypass_turn_and_continuations_never_bypass(
        client, db, auth_headers, auth_user):
    # Server-side mode check; a platform-driven continuation never inherits the turn's mode
    from app.models import Project
    from app.services.workflow_runs.octryx.continuation_marker import _device_target

    device, _ = await device_with_grant(db, auth_user)
    device_hub._connections[device.id] = RecordingConnection(device.id)
    session = await chat_session(db, auth_user)
    project = await db.get(Project, session.project_id)
    project.config = {**(project.config or {}), "agent_gateway_policy": {
        **((project.config or {}).get("agent_gateway_policy") or {}), "bypass_permissions": "disabled"}}
    await db.commit()
    refused = await client.post("/chat/api/send", headers=auth_headers, json={
        "prompt": "Fix it", "session_id": session.id,
        "execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed",
                             "permission_mode": "bypassPermissions"}})
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "bypass_disabled_in_workspace"
    session.metadata_ = {"execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER,
                                              "profile": "governed", "permission_mode": "bypassPermissions"}}
    assert _device_target(session)["permission_mode"] == ""


@pytest.mark.asyncio
async def test_a_turn_follows_the_persons_role_in_the_workspace(client, db, auth_headers, auth_user):
    """Each role's ceiling per Workspace (here admins may not bypass); a viewer's turn runs in plan
    mode whatever was picked; the Workspace info tells the app which modes are offered."""
    from app.models import Project
    from app.models.security.user import UserProject
    from tests.devices.device_support import member_with_headers

    device, _ = await device_with_grant(db, auth_user)
    connection = RecordingConnection(device.id)
    device_hub._connections[device.id] = connection
    session = await chat_session(db, auth_user)
    membership = await db.get(UserProject, (auth_user.id, session.project_id))
    if membership is None:
        db.add(UserProject(user_id=auth_user.id, project_id=session.project_id, role="member"))
    else:
        membership.role = "member"  # a platform admin who is only a member here
    project = await db.get(Project, session.project_id)
    policy = dict((project.config or {}).get("agent_gateway_policy") or {})
    project.config = {**(project.config or {}), "agent_gateway_policy": {**policy, "role_modes": {"admin": "edit"}}}
    await db.commit()

    refused = await client.post("/chat/api/send", headers=auth_headers, json={
        "prompt": "Fix it", "session_id": session.id,
        "execution_target": {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed",
                             "permission_mode": "bypassPermissions"}})
    assert refused.status_code == 409
    assert refused.json()["detail"]["reason"] == "bypass_requires_workspace_owner"
    info = await client.get(f"/api/v1/workspaces/{session.project_id}/agent-gateway/device-runs", headers=auth_headers)
    assert info.json()["session_modes"] == ["plan", "default", "acceptEdits"]

    viewer, viewer_headers = await member_with_headers(client, db, "role-viewer")
    db.add(UserProject(user_id=viewer.id, project_id=session.project_id, role="viewer"))
    viewer_device, _ = await device_with_grant(db, viewer, name="Viewer Mac")
    viewer_connection = RecordingConnection(viewer_device.id)
    device_hub._connections[viewer_device.id] = viewer_connection
    await db.commit()
    started = await client.post("/chat/api/send", headers=viewer_headers, json={
        "prompt": "What does this do?", "project_id": session.project_id,
        "execution_target": {"kind": "device", "device_id": viewer_device.id, "folder": FOLDER,
                             "profile": "governed", "permission_mode": "acceptEdits"}})
    assert started.status_code == 200, started.text
    await DeviceJobHandlers().tick(db, viewer_connection)
    assert viewer_connection.sent[-1][1]["permission_mode"] == "plan"
    info = await client.get(f"/api/v1/workspaces/{session.project_id}/agent-gateway/device-runs",
                            headers=viewer_headers)
    assert info.json()["session_modes"] == ["plan"]
