"""The published agent's tools deny holds at dispatch on server, device and MCP, with zero I/O for a denied tool."""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, AgentPresence
from app.services import agent_tools_deny, mcp_seat_analysis_guard
from app.services.agent_tools_deny import NATIVE_EQUIVALENTS, native_tool_denied, run_session_mcp_refusal
from app.services.workflow_runs.octryx.hooks import run_pre_tool_use
from app.tools import registry
from app.tools.context import ToolContext
from tests.agent_definition_revision_fixtures import make_project
from tests.platform_agent_publish_support import publish_edit
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_octryx_platform_agent import _run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]
MCP = "mcp__octryx-knowledge__"


class _CountingTool:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, params, context):
        self.calls += 1
        return {"ok": True}


async def _deny_for_engineer(db, *tools: str) -> None:
    row = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == "engineer"))).scalar_one()
    row.tools_deny_json = '["' + '","'.join(tools) + '"]'
    await publish_edit(db, row, instructions=row.system_prompt)


async def _bound_session_key(db, session) -> str:
    project = await make_project(db)
    key = str(uuid.uuid4())
    db.add(AgentPresence(id=str(uuid.uuid4()), session_key=key, session_id=session.id, user_id=session.user_id,
                         project_id=project.id, profile="device", client="octryx-claude", device_key="device-deny"))
    await db.flush()
    return key


async def test_the_registry_refuses_a_denied_tool_with_zero_io_and_runs_the_others(db, monkeypatch):
    denied, allowed = _CountingTool(), _CountingTool()
    monkeypatch.setitem(registry.TOOL_REGISTRY, "web_fetch", denied)
    monkeypatch.setitem(registry.TOOL_REGISTRY, "web_search", allowed)
    context = ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={}, db=db,
                          agent_definition={"toolsDeny": ["web_fetch"], "toolSurface": "governed"})
    refused = await registry.execute_tool("web_fetch", {"url": "https://example.test"}, context)
    assert refused["status"] == "denied" and refused["reason"] == "agent_tools_deny" and denied.calls == 0
    ran = await registry.execute_tool("web_search", {"query": "x"}, context)
    assert allowed.calls == 1, ran
    context.agent_definition = {"toolsDeny": [], "toolSurface": "governed"}
    await registry.execute_tool("web_fetch", {"url": "https://example.test"}, context)
    assert denied.calls == 1


async def test_a_run_bound_device_session_cannot_call_a_denied_platform_mcp_tool(db, monkeypatch):
    await _deny_for_engineer(db, "knowledge_search")
    _run_row, session = await _run(db, "engineer")
    key = await _bound_session_key(db, session)
    assert (await run_session_mcp_refusal(db, key, "knowledge_search"))["reason"] == "agent_tools_deny"
    assert await run_session_mcp_refusal(db, key, "knowledge_read") is None
    assert await run_session_mcp_refusal(db, None, "knowledge_search") is None

    @contextlib.asynccontextmanager
    async def shared():
        yield db

    monkeypatch.setattr(mcp_seat_analysis_guard, "async_session_factory", shared)
    calls = []

    async def call(name, arguments):
        calls.append(name)
        return {"ok": True}

    request = SimpleNamespace(headers={"x-octryx-session": key})
    server = SimpleNamespace(get_context=lambda: SimpleNamespace(request_context=SimpleNamespace(request=request)))
    guard = mcp_seat_analysis_guard.seat_analysis_tool_guard(lambda _ctx: ("u", None, None, None))
    refused = await guard(server, "knowledge_search", {}, call)
    assert refused.isError and calls == []
    await guard(server, "knowledge_read", {}, call)
    assert calls == ["knowledge_read"]


async def test_the_device_pre_tool_use_denies_the_mcp_tool_and_its_explicit_native_equivalent(db):
    await _deny_for_engineer(db, "knowledge_search", "web_fetch")
    _run_row, session = await _run(db, "engineer")

    async def decide(tool_name: str, tool_input: dict | None = None):
        answer = await run_pre_tool_use(db, session=session, policy=None,
                                        hook_input={"tool_name": tool_name, "tool_input": tool_input or {}})
        return answer[0]

    mcp = await decide(MCP + "knowledge_search", {"query": "x"})
    assert mcp is not None and mcp.reason == "agent_tools_deny"
    native = await decide("WebFetch", {"url": "https://example.test"})
    assert native is not None and native.reason == "agent_tools_deny" and "web_fetch" in native.message
    assert await decide("Read", {"file_path": "README.md"}) is None
    assert await decide(MCP + "knowledge_read", {"source_key": "k"}) is None


async def test_native_equivalents_are_an_explicit_table_not_a_name_heuristic():
    assert native_tool_denied("WebFetch", ["web_fetch"]) == "web_fetch"
    assert native_tool_denied("Read", ["read_workspace_file"]) == "read_workspace_file"
    # A deny without a table entry denies no native tool, however similar the name looks.
    assert native_tool_denied("WebFetch", ["http_request"]) is None
    assert native_tool_denied("Grep", ["code_search"]) is None
    assert all(name.islower() for name in NATIVE_EQUIVALENTS)
    assert agent_tools_deny.REASON_AGENT_TOOLS_DENY == "agent_tools_deny"
