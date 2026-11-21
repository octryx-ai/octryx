"""Session-generated files never run on the platform's origin: ``/chat/api/artifact``
and the HTML preview carry a sandbox CSP and ``nosniff``, so a generated page opened directly gets an opaque origin
and its scripts cannot call the APIs or read storage as the viewer."""

from __future__ import annotations

import pytest

from tests.test_security_artifact_access_phase2 import _register_and_login_user


async def _session_file(client, auth_headers, tmp_path, name: str, content: str):
    base = tmp_path / "session-workspaces"
    settings = await client.put("/admin/chat/api/panel/runtime-settings", headers=auth_headers,
                                json={"session_workspace_base_dir": str(base), "session_workspace_max_age_hours": 24})
    assert settings.status_code == 200
    headers = await _register_and_login_user(client, auth_headers, username=f"sandbox-{name.replace('.', '-')}")
    session = await client.post("/api/v1/sessions", json={"agent_type": "diagnosis"}, headers=headers)
    assert session.status_code == 200, session.text
    path = base / session.json()["id"] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return headers, path


@pytest.mark.asyncio
async def test_a_generated_html_file_is_served_into_a_sandbox(client, auth_headers, tmp_path):
    headers, path = await _session_file(client, auth_headers, tmp_path, "report.html",
                                        "<script>fetch('/api/v1/auth/me')</script>")

    opened = await client.get("/admin/chat/api/artifact", params={"path": str(path)}, headers=headers)
    preview = await client.get("/admin/chat/api/artifact-preview", params={"path": str(path)}, headers=headers)

    for response in (opened, preview):
        assert response.status_code == 200, response.text
        csp = response.headers["content-security-policy"]
        assert csp.startswith("sandbox") and "allow-same-origin" not in csp
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_a_download_keeps_the_sandbox_and_the_attachment(client, auth_headers, tmp_path):
    headers, path = await _session_file(client, auth_headers, tmp_path, "image.svg", "<svg onload='alert(1)'/>")

    response = await client.get("/admin/chat/api/artifact", params={"path": str(path), "download": "true"},
                                headers=headers)

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    assert "allow-same-origin" not in response.headers["content-security-policy"]
