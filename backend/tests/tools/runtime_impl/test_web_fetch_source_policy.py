"""The chat's ``web_fetch`` checks the governed source registry, with the same function as MCP."""

from __future__ import annotations

import pytest

from app.models import Project
from app.services.web_search.registry import put_source
from app.tools.context import ToolContext
from app.tools.runtime_impl import _runtime_bash_web
from app.tools.runtime_impl._runtime_bash_web import WebFetchTool
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace


class _Response:
    status_code = 200
    content = b"<html><body>ok</body></html>"
    headers = {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def fetched(monkeypatch):
    urls: list[str] = []

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            urls.append(url)
            return _Response()

    monkeypatch.setattr(_runtime_bash_web, "public_web_client", lambda **_: _Client())
    return urls


async def _context(db, mode: str) -> ToolContext:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    (await db.get(Project, workspace_id)).config = {"web_search_policy": {"mode": mode}}
    await put_source(db, project_id=workspace_id, pattern="docs.spring.io/spring-boot", state="trusted", user_id=None)
    await put_source(db, project_id=workspace_id, pattern="blocked.example.org", state="blocked", user_id=None)
    await db.commit()
    return ToolContext(user_id=member_id, project_ids=[workspace_id], roles=[], session_id=None, db=db,
                       project_config={"project_id": workspace_id})


async def test_the_chat_web_fetch_holds_the_source_registry(db, fetched):
    trusted_only = await _context(db, "trusted_only")
    tool = WebFetchTool()

    blocked = await tool.execute({"url": "https://www.pornhub.com/view"}, trusted_only)
    assert (blocked["state"], blocked["reason"]) == ("denied", "source_blocked")
    workspace_blocked = await tool.execute({"url": "https://blocked.example.org/a"}, trusted_only)
    assert workspace_blocked["reason"] == "source_blocked"
    untrusted = await tool.execute({"url": "https://example.org/page"}, trusted_only)
    assert (untrusted["state"], untrusted["reason"]) == ("denied", "source_not_trusted")
    assert fetched == []

    trusted = await tool.execute({"url": "https://docs.spring.io/spring-boot/upgrading.html"}, trusted_only)
    assert "error" not in trusted and fetched == ["https://docs.spring.io/spring-boot/upgrading.html"]

    open_mode = await _context(db, "open")
    assert "error" not in await tool.execute({"url": "https://example.org/page"}, open_mode)
    assert (await tool.execute({"url": "https://blocked.example.org/a"}, open_mode))["reason"] == "source_blocked"
    assert (await tool.execute({"url": "ftp://example.org/x"}, open_mode))["reason"] == "invalid_url"
