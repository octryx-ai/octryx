"""Tests for GET /chat/api/artifact-image (server-rendered diagram PNGs)."""

from __future__ import annotations

import stat
import uuid

import pytest
from sqlalchemy import select

from app.models import Session, ToolCall, User
from app.services.diagram_export_service import DIAGRAM_PNG_CACHE_DIR_ENV, DRAWIO_BIN_ENV

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

VALID_XML = (
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="Hello" style="rounded=1;" vertex="1" parent="1">'
    '<mxGeometry x="40" y="40" width="120" height="60" as="geometry"/>'
    "</mxCell></root></mxGraphModel>"
)

_FAKE_DRAWIO = """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
out = args[args.index("-o") + 1]
with open(out, "wb") as handle:
    handle.write(b"\\x89PNG\\r\\n\\x1a\\n" + b"fake-png-body")
"""


def _install_fake_drawio(tmp_path, monkeypatch) -> None:
    binary = tmp_path / "fake-drawio"
    binary.write_text(_FAKE_DRAWIO, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv(DRAWIO_BIN_ENV, str(binary))
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))


async def _seed_admin_diagram(db, diagram_id: str) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        tool_name="create_diagram",
        status="success",
        result={"diagram_id": diagram_id, "diagram_xml": VALID_XML, "title": "Topology"},
    )
    db.add_all([session, tool_call])
    await db.flush()


@pytest.mark.asyncio
async def test_artifact_image_requires_authentication(client):
    resp = await client.get("/chat/api/artifact-image", params={"path": "diagram://diag-1"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_artifact_image_returns_png(client, db, auth_headers, tmp_path, monkeypatch):
    _install_fake_drawio(tmp_path, monkeypatch)
    await _seed_admin_diagram(db, "diag-png")

    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "diagram://diag-png"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(PNG_MAGIC)


@pytest.mark.asyncio
async def test_artifact_image_answers_503_when_renderer_unavailable(
    client, db, auth_headers, tmp_path, monkeypatch
):
    monkeypatch.setenv(DRAWIO_BIN_ENV, str(tmp_path / "missing-drawio"))
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))
    await _seed_admin_diagram(db, "diag-unavailable")

    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "diagram://diag-unavailable"},
        headers=auth_headers,
    )

    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("renderer_unavailable")


@pytest.mark.asyncio
async def test_artifact_image_render_failure_never_echoes_cli_output(
    client, db, auth_headers, tmp_path, monkeypatch
):
    binary = tmp_path / "failing-drawio"
    binary.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.stderr.write('secret-host.internal token=abc')\nsys.exit(3)\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv(DRAWIO_BIN_ENV, str(binary))
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))
    await _seed_admin_diagram(db, "diag-fails")

    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "diagram://diag-fails"},
        headers=auth_headers,
    )

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "diagram_render_failed error_type=DiagramRenderError" in detail
    assert "secret-host" not in detail


@pytest.mark.asyncio
async def test_artifact_image_rejects_non_diagram_paths(client, auth_headers):
    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "/etc/passwd"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_artifact_image_rejects_unsupported_scale(client, db, auth_headers, tmp_path, monkeypatch):
    _install_fake_drawio(tmp_path, monkeypatch)
    await _seed_admin_diagram(db, "diag-scale")

    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "diagram://diag-scale", "scale": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_artifact_image_unknown_diagram_is_404(client, auth_headers, tmp_path, monkeypatch):
    _install_fake_drawio(tmp_path, monkeypatch)
    resp = await client.get(
        "/chat/api/artifact-image",
        params={"path": "diagram://does-not-exist"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
