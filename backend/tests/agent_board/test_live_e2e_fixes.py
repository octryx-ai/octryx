"""Two-agent flow: every claim tool answer the agent sees carries the content_is_data notice."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from app.services import mcp_work_claim_tools as tools
from tests.agent_board.support import agent, seed_item, seed_presence
from tests.agent_board.work_item_claims_support import _claim, _two_members

NOTICE = tools.CONTENT_IS_DATA


async def _server(db, monkeypatch, user_id: str, grant_id: str | None) -> FastMCP:
    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(tools, "async_session_factory", session)
    monkeypatch.setattr(tools, "request_headers", lambda ctx: {})
    monkeypatch.setattr(tools, "mcp_client_name", lambda ctx: "e2e")

    async def no_binding(db, *, grant_id, user_id):
        return None  # a grant without a Workspace binding: the user's membership is the scope

    monkeypatch.setattr("app.services.mcp_work_access.resolve_work_grant_binding", no_binding)
    server = FastMCP("t")
    tools.register_work_claim_tools(server, lambda ctx: (user_id, None, grant_id, ("work:manage",)))
    return server


def _answer(result: Any) -> dict[str, Any]:
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


@pytest.mark.asyncio
async def test_who_is_working_on_carries_the_notice_as_the_agent_sees_it(db, monkeypatch):
    workspace_id, anna, ben = await _two_members(db)
    item = await seed_item(db, workspace_id, "BRD-7", title="Rework billing export")
    await _claim(db, await agent(db, anna), item, paths=["src/billing"])
    await seed_presence(db, anna, workspace_id, work_item_key="BRD-7")
    server = await _server(db, monkeypatch, ben, None)
    for arguments in ({"query": "BRD-7"}, {"paths": ["src/billing"]}, {"query": "nothing"}, {}):
        answer = _answer(await server.call_tool("who_is_working_on", arguments))
        assert answer["content_is_data"] == NOTICE, arguments
    claimed = _answer(await server.call_tool("work_item_claim", {"work_item_id": item.id}))
    assert claimed["content_is_data"] == NOTICE
