import json
import uuid

import pytest
from sqlalchemy import select

from app.models import ChangePreview, User
from app.services.approval import ensure_approval_request


@pytest.mark.asyncio
async def test_session_workspace_api_serializes_approval_change_preview_changes(client, auth_headers, db, tmp_path):
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

    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    approval = await ensure_approval_request(
        db,
        requested_by=admin.id,
        session_id=session_id,
        action="Approve command execution for bash",
        reason="Need approval for workspace change preview",
    )
    preview = ChangePreview(
        id=str(uuid.uuid4()),
        session_id=session_id,
        approval_id=approval.id,
        tool_name="bash",
        request_fingerprint="workspace-preview-fingerprint",
        preview_json=json.dumps({"summary": "Preview summary", "files": ["repo/main.py"]}),
    )
    db.add(preview)
    await db.commit()

    workspace_resp = await client.get(
        f"/admin/chat/api/sessions/{session_id}/workspace",
        headers=auth_headers,
    )
    assert workspace_resp.status_code == 200
    payload = workspace_resp.json()
    assert len(payload["changes"]) == 1
    assert payload["changes"][0]["approvalId"] == approval.id
    assert payload["changes"][0]["toolName"] == "bash"
    assert payload["changes"][0]["preview"]["summary"] == "Preview summary"
