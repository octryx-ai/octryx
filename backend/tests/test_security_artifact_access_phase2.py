from __future__ import annotations

from pathlib import Path

import pytest

from app.web._helpers import api_guards


async def _register_and_login_user(client, admin_headers: dict[str, str], *, username: str) -> dict[str, str]:
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "testpass123",
            "display_name": username.title(),
        },
        headers=admin_headers,
    )
    assert register_resp.status_code == 200, register_resp.text

    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "testpass123"},
    )
    assert login_resp.status_code == 200, login_resp.text
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_non_admin_cannot_access_global_office_sample_artifact(client, auth_headers):
    user_headers = await _register_and_login_user(client, auth_headers, username="artifact-user")
    sample_path = api_guards.WORKSPACE_ROOT / "data" / "office-samples" / "project-proposal.docx"

    resp = await client.get(
        "/admin/chat/api/artifact",
        params={"path": str(sample_path)},
        headers=user_headers,
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Global artifact access requires admin role"


@pytest.mark.asyncio
async def test_session_owner_can_access_session_workspace_artifact(client, auth_headers, tmp_path):
    workspace_base = tmp_path / "session-workspaces"
    settings_resp = await client.put(
        "/admin/chat/api/panel/runtime-settings",
        headers=auth_headers,
        json={
            "session_workspace_base_dir": str(workspace_base),
            "session_workspace_max_age_hours": 24,
        },
    )
    assert settings_resp.status_code == 200

    user_headers = await _register_and_login_user(client, auth_headers, username="workspace-owner")
    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=user_headers,
    )
    assert session_resp.status_code == 200, session_resp.text

    session_id = session_resp.json()["id"]
    artifact_path = workspace_base / session_id / "notes.txt"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("workspace artifact", encoding="utf-8")

    resp = await client.get(
        "/admin/chat/api/artifact",
        params={"path": str(artifact_path)},
        headers=user_headers,
    )

    assert resp.status_code == 200
    assert resp.text == "workspace artifact"


@pytest.mark.asyncio
async def test_admin_can_access_allowed_global_office_sample_artifact(client, auth_headers):
    sample_path = api_guards.WORKSPACE_ROOT / "data" / "office-samples" / "project-proposal.docx"
    assert Path(sample_path).exists()

    resp = await client.get(
        "/admin/chat/api/artifact",
        params={"path": str(sample_path)},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.content
