"""Shared helpers for the test_device_job_session_parity_* modules."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Session, ToolCall, WorkflowRun
from app.models.security.device import UserDevice
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.oauth_provider import mint_access_token
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _phase_turn,
    _settle,
    _workspace,
    submitted,
    systems,
)

GATEWAY = "/api/v1/agent-gateway/sessions"


B_KEY = "feature-delivery-tdd"


CONFIRMED = "tests/test_totals.py"


TOTALS_TEST = "from pay.totals import round_total\n\n\ndef test_rounds_half_up():\n    assert round_total(2.5) == 3\n"


HEAD = "1" * 40


REMOTE = "https://scm.stub.test/acme/pay.git"


async def _device(db, user, folders: list[str]) -> str:
    from app.models.security.user import UserProject

    workspace_id = (await db.execute(select(WorkflowRun.project_id).order_by(WorkflowRun.created_at.desc()))
                    ).scalars().first()
    member = (await db.execute(select(UserProject).where(UserProject.user_id == user.id,
                                                         UserProject.project_id == workspace_id))).scalars().first()
    if member is None:
        db.add(UserProject(user_id=user.id, project_id=workspace_id, role="admin"))
    grant = OAuthGrant(user_id=user.id, client_id=f"oec_dev_{uuid.uuid4().hex[:6]}", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.flush()
    device = UserDevice(owner_user_id=user.id, name="Box", name_key=f"box-{uuid.uuid4().hex[:6]}", os="macos",
                        public_key="x", folders=folders, grant_id=grant.id)
    db.add(device)
    await db.flush()
    grant.device_id = device.id
    await db.commit()
    token, _ = mint_access_token(user_id=user.id, client_id=grant.client_id, grant_id=grant.id,
                                 scopes=[SCOPE_MODEL_INVOKE], resource=GATEWAY_AUDIENCE)
    return token


def _headers(token: str, workspace_id: str, run_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Octryx-Session": str(uuid.uuid4()),
            "X-Octryx-Workspace": workspace_id, "X-Octryx-Workflow-Run": run_id}


def _binding(root: str, remote: str = REMOTE) -> dict:
    return {"remote_url": remote, "head_commit": HEAD, "head_dirty": False, "head_pushed": True, "branch": "main",
            "root": root}


async def _gateway(db, headers: dict) -> Session:
    key = headers["X-Octryx-Session"]
    return (await db.execute(select(Session).where(
        Session.metadata_["gateway_session_key"].as_string() == key))).scalar_one()


async def _register(client, headers: dict) -> dict:
    answer = await client.post(f"{GATEWAY}/register", headers=headers,
                               json={"profile": "governed", "client": "octryx-claude-device"})
    return {"status": answer.status_code, **answer.json()}


async def _b_at_tests_first(client, auth_headers, db, systems) -> tuple[object, str, Path]:  # noqa: F811
    project, item = await _workspace(db, systems)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id})
    assert started.status_code == 200, started.text
    run_id, session_id = started.json()["run"]["id"], started.json()["session_id"]
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "clarify"
    read = {"tool_name": "read_workspace_file", "status": "success", "result": {}}
    contract = {"criteria": [{"id": "AC1", "text": "Totals round half up", "tests": [f"{CONFIRMED}::test_rounds_half_up"],
                              "command": f"pytest -v {CONFIRMED}"}]}
    await _phase_turn(db, session_id, [read, await submitted(db, session_id, "submit_test_contract", contract)])
    waiting = (await client.get(f"/api/v1/workflow-runs/{run_id}", headers=auth_headers)).json()["run"]["waiting"]
    confirmed = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    assert confirmed.json()["run"]["current_node"]["id"] == "tests_first", confirmed.text
    run = await db.get(WorkflowRun, run_id)
    assert run.repository == "github:acme/pay"
    return project, run_id, Path(run.context["local_path"])


def _call(gateway, tool: str, *, at, ok: bool = True, excerpt: str = "", **parameters) -> ToolCall:
    return ToolCall(session_id=gateway.id, tool_name=tool, parameters={"source": "gateway", **parameters},
                    result={"is_error": not ok, "excerpt": excerpt}, status="success", created_at=at)


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
