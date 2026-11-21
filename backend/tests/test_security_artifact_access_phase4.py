from __future__ import annotations

import pytest

from app.web import _context as web_context
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
async def test_admin_cannot_inline_preview_global_html_artifact(client, auth_headers, monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace-root"
    chat_upload_root = workspace_root / "uploads" / "chat" / "draft-abc"
    artifact_path = chat_upload_root / "report.html"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("<html><body>report</body></html>", encoding="utf-8")

    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", workspace_root.resolve())
    monkeypatch.setattr(api_guards, "WORKSPACE_ROOT", workspace_root.resolve())

    resp = await client.get(
        "/admin/chat/api/artifact-preview",
        params={"path": str(artifact_path)},
        headers=auth_headers,
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Inline preview is not allowed for global HTML artifacts"


@pytest.mark.asyncio
async def test_session_owner_can_still_inline_preview_session_workspace_html_artifact(
    client,
    auth_headers,
    tmp_path,
):
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

    user_headers = await _register_and_login_user(client, auth_headers, username="workspace-preview-owner")
    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=user_headers,
    )
    assert session_resp.status_code == 200, session_resp.text

    session_id = session_resp.json()["id"]
    artifact_path = workspace_base / session_id / "preview.html"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("<html><body>workspace preview</body></html>", encoding="utf-8")

    resp = await client.get(
        "/admin/chat/api/artifact-preview",
        params={"path": str(artifact_path)},
        headers=user_headers,
    )

    assert resp.status_code == 200
    assert "workspace preview" in resp.text
    assert resp.headers.get("content-type", "").startswith("text/html")
