from __future__ import annotations

import asyncio
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.models import Session
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.sources.repository_snapshot.binding import BINDING_METADATA_KEY
from app.services.knowledge.sources.repository_snapshot.protocol_types import (
    BindRequest,
    BindResponse,
    CompleteRequest,
    CompleteResponse,
    FilesRequest,
    FilesResponse,
    ManifestRequest,
    ManifestResponse,
    SessionBinding,
    SnapshotCursor,
)
from tests.services.agent_gateway.test_agent_gateway_repository_routes import (  # noqa: F401 - fixture
    _gateway_headers,
    evidence_runtime,
)
from tests.typed_dict_support import shape_problems

CLIENT_DIR = Path(__file__).resolve().parents[5] / "clients" / "octryx-claude"
PREFIX = "/api/v1/agent-gateway/sessions/repository"
REMOTE = "https://gitlab.example.test/team/app.git"
SHAPES = {
    PREFIX: (BindRequest, BindResponse),
    f"{PREFIX}/manifest": (ManifestRequest, ManifestResponse),
    f"{PREFIX}/files": (FilesRequest, FilesResponse),
    f"{PREFIX}/complete": (CompleteRequest, CompleteResponse),
}
_FORWARDED = ("authorization", "content-type")


def _launcher():
    if str(CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(CLIENT_DIR))
    from octryx_claude import platform, snapshot

    return platform, snapshot


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    *args], cwd=root, check=True, capture_output=True)


def _checkout(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "gitconfig").write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "pom.xml").write_text("<project><artifactId>app</artifactId></project>\n")
    (root / "src" / "App.java").write_text("class App {}\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "start")
    _git(root, "remote", "add", "origin", REMOTE)
    return root


async def _cursor(db, project_id: str) -> dict:
    connector = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == project_id).execution_options(populate_existing=True))).scalar_one()
    return dict(connector.cursor)


class _Bridge(httpx.BaseTransport):
    def __init__(self, client, loop, db, project_id: str) -> None:
        self.client, self.loop, self.db, self.project_id = client, loop, db, project_id
        self.calls: list[tuple[str, dict, dict]] = []
        self.open_cursors: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return asyncio.run_coroutine_threadsafe(self._forward(request), self.loop).result(timeout=120)

    async def _forward(self, request: httpx.Request) -> httpx.Response:
        headers = {key: value for key, value in request.headers.items()
                   if key in _FORWARDED or key.startswith("x-octryx-")}
        response = await self.client.post(request.url.path, headers=headers, content=request.content)
        self.calls.append((request.url.path, json.loads(request.content), response.json()))
        if request.url.path.endswith("/manifest"):
            self.open_cursors.append(await _cursor(self.db, self.project_id))
        return httpx.Response(response.status_code, json=response.json(), headers={
            key: value for key, value in response.headers.items() if key.startswith("x-octryx-")})


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
async def test_the_launchers_snapshot_calls_and_the_platforms_answers_match_the_protocol_types(
    client, db, auth_headers, evidence_runtime, tmp_path, monkeypatch  # noqa: F811
):
    platform, snapshot = _launcher()
    headers, project, _ = await _gateway_headers(db)
    policy = f"/api/v1/workspaces/{project.id}/knowledge/repositories/policy"
    assert (await client.put(policy, headers=auth_headers, json={"allow_local_snapshots": True})).status_code == 200
    token = headers["Authorization"].removeprefix("Bearer ")
    monkeypatch.setattr(platform, "get_access_token", lambda state, audience, http: token)
    context = platform.SessionContext("http://test", headers["X-Octryx-Session"], project.id)
    bridge = _Bridge(client, asyncio.get_running_loop(), db, project.id)

    outcome = await asyncio.to_thread(snapshot.run_code_intelligence, None, context, _checkout(tmp_path, monkeypatch),
                                      http=httpx.Client(transport=bridge), out=io.StringIO())

    assert outcome.state == "indexed", outcome
    assert [path for path, _, _ in bridge.calls] == list(SHAPES)
    for path, sent, answered in bridge.calls:
        request_type, response_type = SHAPES[path]
        assert shape_problems(sent, request_type, path) == []
        assert shape_problems(answered, response_type, path) == []
    [open_cursor] = bridge.open_cursors
    assert "snapshot" in open_cursor and shape_problems(open_cursor, SnapshotCursor, "cursor") == []
    assert shape_problems(await _cursor(db, project.id), SnapshotCursor, "cursor") == []
    session = (await db.execute(select(Session).where(
        Session.metadata_["gateway_session_key"].as_string() == headers["X-Octryx-Session"]))).scalar_one()
    assert shape_problems(session.metadata_[BINDING_METADATA_KEY], SessionBinding, "binding") == []
