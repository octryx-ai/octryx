"""The launcher's repository endpoints and the confirmation ask over HTTP."""

from __future__ import annotations

import base64
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Project, Session, ToolCall, User
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import GATEWAY_AUDIENCE, SCOPE_MODEL_INVOKE
from app.services.knowledge.sources.repository_snapshot.snapshot_files import git_blob_sha1
from app.services.oauth_provider import mint_access_token
from tests.agent_gateway_hook_support import STATE_ROOT, confirm_hook_input, new_hook_key
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_runtime_support import set_evidence_runtime

BASE = "/api/v1/agent-gateway/sessions"
HEAD = "1" * 40
POM = b"<project>\n  <properties>\n    <java.version>11</java.version>\n  </properties>\n</project>\n"


@pytest.fixture
def evidence_runtime(monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.test")
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, evidence_index
    finally:
        set_evidence_runtime(None)


async def _gateway_headers(db) -> tuple[dict[str, str], Project, User]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_gw_{uuid.uuid4().hex[:6]}", scopes=[SCOPE_MODEL_INVOKE])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id, client_id=grant.client_id, grant_id=grant.id, scopes=[SCOPE_MODEL_INVOKE],
        resource=GATEWAY_AUDIENCE,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Octryx-Session": str(uuid.uuid4()),
        "X-Octryx-Workspace": project.id,
    }
    return headers, project, admin


@pytest.mark.asyncio
async def test_bind_snapshot_view_and_policy_over_http(client, db, auth_headers, evidence_runtime):
    _, evidence_index = evidence_runtime
    headers, project, admin = await _gateway_headers(db)
    binding = {"remote_url": "https://gitlab.example.test/team/app.git", "head_commit": HEAD, "head_dirty": False,
               "head_pushed": True, "branch": "main"}

    policy_url = f"/api/v1/workspaces/{project.id}/knowledge/repositories/policy"
    assert (await client.get(policy_url, headers=auth_headers)).json()["allow_local_snapshots"] is False
    denied = await client.post(f"{BASE}/repository", headers=headers, json=binding)
    assert denied.status_code == 200
    assert denied.json()["snapshot"] == {"state": "denied", "reason": "local_snapshots_not_allowed"}
    key = headers["X-Octryx-Session"]
    session = (await db.execute(select(Session).where(Session.metadata_["gateway_session_key"].as_string() == key)))
    assert session.scalar_one().metadata_["repository_binding"]["links"] == "platform"
    refused = await client.post(f"{BASE}/repository/manifest", headers=headers, json={"head_commit": HEAD, "files": []})
    assert (refused.status_code, refused.headers["x-octryx-gateway-reason"]) == (
        403, "local_snapshots_not_allowed"
    )

    put = await client.put(policy_url, headers=auth_headers, json={"allow_local_snapshots": True})
    assert put.status_code == 200 and put.json()["allow_local_snapshots"] is True
    bound = (await client.post(f"{BASE}/repository", headers=headers, json=binding)).json()
    assert bound["snapshot"]["state"] == "allowed"
    blob = git_blob_sha1(POM)
    manifest = {"head_commit": HEAD, "files": [{"path": "pom.xml", "blob_sha": blob, "size": len(POM)}]}
    assert (await client.post(f"{BASE}/repository/manifest", headers=headers, json=manifest)).json()["wanted"] == [
        "pom.xml"
    ]
    files = {"head_commit": HEAD, "files": [
        {"path": "pom.xml", "blob_sha": blob, "content_base64": base64.b64encode(POM).decode()}
    ]}
    uploaded = (await client.post(f"{BASE}/repository/files", headers=headers, json=files)).json()
    assert uploaded["results"][0]["outcome"] == "ingested"
    completed = (await client.post(f"{BASE}/repository/complete", headers=headers, json={"head_commit": HEAD})).json()
    assert (completed["state"], completed["files_indexed"]) == ("indexed", 1)

    viewer = f"/api/v1/workspaces/{project.id}/knowledge/repositories/{bound['binding']['connector_key']}/blob"
    view = await client.get(f"{viewer}/{HEAD}/pom.xml", headers=auth_headers)
    assert view.status_code == 200 and view.json()["blob_sha"] == blob
    assert "java.version" in "".join(span["text"] for span in view.json()["spans"])
    unknown_commit = await client.get(f"{viewer}/{'2' * 40}/pom.xml", headers=auth_headers)
    assert unknown_commit.status_code == 404
    assert unknown_commit.json()["detail"]["state"] == "blob_superseded"

    # A new commit changes pom.xml. The old link (with its blob) keeps opening the cited content;
    # a bare old commit is blob_superseded and names the current commit.
    head2 = "3" * 40
    pom2 = POM.replace(b"11", b"17")
    blob2 = git_blob_sha1(pom2)
    await client.post(f"{BASE}/repository", headers=headers, json={**binding, "head_commit": head2})
    manifest2 = {"head_commit": head2, "files": [{"path": "pom.xml", "blob_sha": blob2, "size": len(pom2)}]}
    assert (await client.post(f"{BASE}/repository/manifest", headers=headers, json=manifest2)).json()["wanted"] == [
        "pom.xml"
    ]
    files2 = {"head_commit": head2, "files": [
        {"path": "pom.xml", "blob_sha": blob2, "content_base64": base64.b64encode(pom2).decode()}
    ]}
    assert (await client.post(f"{BASE}/repository/files", headers=headers, json=files2)).json()["results"][0][
        "outcome"
    ] == "ingested"
    await client.post(f"{BASE}/repository/complete", headers=headers, json={"head_commit": head2})
    old_link = await client.get(f"{viewer}/{HEAD}/pom.xml?blob={blob}", headers=auth_headers)
    assert old_link.status_code == 200
    assert (old_link.json()["blob_sha"], old_link.json()["current"]) == (blob, False)
    assert "<java.version>11" in "".join(span["text"] for span in old_link.json()["spans"])
    bare_old = await client.get(f"{viewer}/{HEAD}/pom.xml", headers=auth_headers)
    assert bare_old.status_code == 404
    assert bare_old.json()["detail"] == {"state": "blob_superseded", "path": "pom.xml", "current_commit": head2}
    new_link = await client.get(f"{viewer}/{head2}/pom.xml?blob={blob2}", headers=auth_headers)
    assert new_link.json()["current"] is True
    assert (await client.get(f"{viewer}/{head2}/pom.xml?blob={'4' * 40}", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_hook_key_registration_and_the_tool_check_ask_over_http(client, db):
    headers, _, _ = await _gateway_headers(db)
    session_key = headers["X-Octryx-Session"]
    key = new_hook_key()
    raw = base64.urlsafe_b64encode(key).decode().rstrip("=")
    body = {"hook_key": raw, "state_root": STATE_ROOT}
    registered = await client.post(f"{BASE}/hook-key", headers=headers, json=body)
    assert registered.json() == {"state": "registered"}
    again = await client.post(f"{BASE}/hook-key", headers=headers, json=body)
    assert (again.status_code, again.headers["x-octryx-gateway-reason"]) == (409, "hook_key_already_registered")

    approval_id = str(uuid.uuid4())
    hook = {**confirm_hook_input(key, session_key=session_key, approval_id=approval_id), "cwd": "/work/repo"}
    answer = await client.post(f"{BASE}/tool-check", headers=headers, json=hook)
    assert answer.status_code == 200
    payload = answer.json()
    assert (payload["decision"], payload["state"]) == ("ask", "needs_confirmation") and payload["confirmation_ticket"]
    tickets = (await db.execute(select(ToolCall).where(ToolCall.status == "confirmation_asked"))).scalars().all()
    assert [row.parameters["approval_id"] for row in tickets] == [approval_id]
    assert all("confirmation_ticket" not in str(row.parameters) and payload["confirmation_ticket"] not in str(
        row.parameters) for row in tickets)
    forged = {**hook, "confirmation_proof": {**hook["confirmation_proof"], "mac": "0" * 64}}
    assert (await client.post(f"{BASE}/tool-check", headers=headers, json=forged)).json()["decision"] == "deny"

    # The session follows the person's permission mode. In plan mode an edit is denied with the
    # closed reason and the hint; in the default mode it may change files inside the session's folder.
    edit = {"hook_event_name": "PreToolUse", "cwd": "/work/repo", "tool_name": "Edit", "tool_use_id": "toolu_e",
            "permission_mode": "plan",
            "tool_input": {"file_path": "/work/repo/pom.xml", "old_string": "a", "new_string": "b"}}
    denied = (await client.post(f"{BASE}/tool-check", headers=headers, json=edit)).json()
    assert (denied["decision"], denied["reason"]) == ("deny", "capability_read_only")
    assert "plan mode" in denied["message"]
    working = (await client.post(f"{BASE}/tool-check", headers=headers,
                                 json={**edit, "permission_mode": "default", "tool_use_id": "toolu_f"})).json()
    assert working["decision"] == "allow"
    curl = {**edit, "tool_name": "Bash",
            "tool_input": {"command": "curl -X POST http://localhost:8090/api/v1/agent-gateway/sessions/tool-check"}}
    assert (await client.post(f"{BASE}/tool-check", headers=headers, json=curl)).json()["reason"] == (
        "platform_credentials_protected"
    )
