"""The platform MCP server's own gate and evidence ledger for a seat analysis session."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.types import CallToolResult
from sqlalchemy import select

from app.models import ToolCall
from app.services import mcp_seat_analysis_guard as guard_module
from app.services.prompt_catalog.mcp_descriptions import CatalogFastMCP
from tests.support.oauth_test_utils import obtain_oauth_tokens
from tests.work_item_analysis.support import MANUAL_HIT, analysis
from tests.work_item_analysis.test_seat_runner import _register, _registered, _seat_env, _submit


def _server(monkeypatch, db, *, key: str | None, user_id: str) -> tuple[CatalogFastMCP, list[str]]:
    ran: list[str] = []

    @asynccontextmanager
    async def same_db():
        yield db

    async def no_prompt_set(server):
        return None

    monkeypatch.setattr(guard_module, "async_session_factory", same_db)
    monkeypatch.setattr(guard_module, "connection_session_key", lambda ctx: key)
    server = CatalogFastMCP(
        "t", prompt_set_for_request=no_prompt_set,
        tool_call_guard=guard_module.seat_analysis_tool_guard(lambda ctx: (user_id, None, None, ())),
    )

    @server.tool(name="knowledge_search")
    async def knowledge_search(query: str) -> dict[str, Any]:
        ran.append("knowledge_search")
        return {"results": [{"text": MANUAL_HIT}]}

    @server.tool(name="knowledge_read")
    async def knowledge_read(ref: str) -> dict[str, Any]:
        ran.append("knowledge_read")
        return {"state": "not_found", "error": f"No source {MANUAL_HIT}"}

    @server.tool(name="work_item_note")
    async def work_item_note(text: str) -> dict[str, Any]:
        ran.append("work_item_note")
        return {"ok": True}

    return server, ran


async def _evidence(db, session_id: str) -> list[ToolCall]:
    return list((await db.execute(select(ToolCall).where(ToolCall.session_id == session_id))).scalars().all())


@pytest.mark.asyncio
async def test_a_tool_outside_the_analysis_set_is_refused_server_side_and_never_runs(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    server, ran = _server(monkeypatch, db, key=key, user_id=env.user.id)

    refused = await server.call_tool("work_item_note", {"text": "x"})

    assert isinstance(refused, CallToolResult) and refused.isError
    assert json.loads(refused.content[0].text)["reason"] == "analysis_tool_not_allowed"
    assert ran == [] and await _evidence(db, session.id) == []


@pytest.mark.asyncio
async def test_the_servers_own_read_tool_runs_are_the_evidence_a_submit_cites(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    server, ran = _server(monkeypatch, db, key=key, user_id=env.user.id)
    assert (await _submit(db, env, key, analysis()))["error_code"] == "analysis_uncited"

    await server.call_tool("knowledge_read", {"ref": "x"})  # an error result is recorded, never cited
    assert (await _submit(db, env, key, analysis()))["error_code"] == "analysis_uncited"
    await server.call_tool("knowledge_search", {"query": "certificate"})

    rows = await _evidence(db, session.id)
    assert ran == ["knowledge_read", "knowledge_search"]
    assert [(row.tool_name, row.parameters["source"], row.result["is_error"]) for row in rows] == [
        ("knowledge_read", "mcp_server", True), ("knowledge_search", "mcp_server", False)]
    stored = await _submit(db, env, key, analysis())
    assert stored["status"] == "succeeded" and stored["stored"] is True


@pytest.mark.asyncio
async def test_another_users_run_with_the_same_key_records_nothing(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    server, ran = _server(monkeypatch, db, key=key, user_id="someone-else")

    await server.call_tool("knowledge_search", {"query": "certificate"})
    refused = await server.call_tool("work_item_note", {"text": "x"})  # the key still narrows the tools

    assert ran == ["knowledge_search"] and refused.isError
    assert await _evidence(db, session.id) == []
    assert (await _submit(db, env, key, analysis()))["error_code"] == "analysis_uncited"


@pytest.mark.asyncio
@pytest.mark.parametrize("named", [False, True])
async def test_a_connection_without_an_analysis_session_keeps_every_tool(client, db, monkeypatch, named):
    env = await _seat_env(db, monkeypatch)
    _, headers = await _register(client, db, env, purpose=None)
    key = headers["x-octryx-session"] if named else None
    server, ran = _server(monkeypatch, db, key=key, user_id=env.user.id)

    result = await server.call_tool("work_item_note", {"text": "x"})

    assert not isinstance(result, CallToolResult) and ran == ["work_item_note"]


@pytest.mark.asyncio
async def test_the_rest_tool_endpoint_refuses_outside_the_analysis_set(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    tokens = await obtain_oauth_tokens(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", "X-Octryx-Session": key}

    refused = await client.post("/api/v1/mcp/knowledge/tools/knowledge_changes", headers=headers,
                                json={"arguments": {"product": "x"}})
    allowed = await client.post("/api/v1/mcp/knowledge/tools/knowledge_search", headers=headers,
                                json={"arguments": {"query": "x"}})

    assert refused.status_code == 200 and refused.json()["result"]["reason"] == "analysis_tool_not_allowed"
    assert allowed.status_code == 200 and allowed.json()["result"].get("reason") != "analysis_tool_not_allowed"
    # The OAuth user is not the session's owner: the run is never the session's evidence.
    assert await _evidence(db, session.id) == []
