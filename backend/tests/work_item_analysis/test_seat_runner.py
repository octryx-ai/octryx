"""The seat analysis runner (``octryx-claude analyze <KEY>``): registration, the fixed tool set, and the governed
submit rules. No model call."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.models import AgentBoardMessage, AgentPresence, Project, Session, ToolCall, WorkItem, WorkItemAnalysis
from app.services import mcp_work_analysis_tools as tools
from app.services.mcp_work_access import WorkGrantScope
from app.services.work_item_analysis.seat_submit import submit_seat_analysis
from tests.agent_gateway.seat_presence_support import REGISTER, _gateway_headers
from tests.services.agent_gateway.test_agent_gateway_control_plane import _pre_tool_use
from tests.work_item_analysis.support import MANUAL_HIT, POLICY, analysis, seed_env

TOOL_CHECK = "/api/v1/agent-gateway/sessions/tool-check"
SEAT_CONFIG = {"agent_gateway_policy": {"seat_mode": "allowed"}, "data_policy": {"classification": "internal"}}
SEAT_SETTINGS = {"model_policy": f"{POLICY}@1", "runner": "seat"}
SEARCH = "mcp__octryx-knowledge__knowledge_search"
EVIDENCE = "knowledge_search"


async def _seat_env(db, monkeypatch, *, settings: dict[str, Any] | None = None, config: dict[str, Any] | None = None):
    return await seed_env(db, monkeypatch, settings=SEAT_SETTINGS if settings is None else settings,
                          project_config=SEAT_CONFIG if config is None else config)


async def _register(client, db, env, *, profile: str = "seat", key: str | None = None, purpose: Any = "work_item_analysis"):
    headers = await _gateway_headers(db, env.user.id, env.workspace_id)
    work_item = env.item.source_key if key is None else key
    if work_item:
        headers["x-octryx-work-item"] = work_item
    body = {"profile": profile, "client": "octryx-claude", "client_version": "0.3.0"}
    if purpose is not None:
        body["purpose"] = purpose
    return await client.post(REGISTER, json=body, headers=headers), headers


def _scope(workspace_id: str) -> WorkGrantScope:
    ids = frozenset({workspace_id})
    return WorkGrantScope(grant_id=None, binding=None, item_project_ids=ids, listing_project_ids=ids)


async def _session(db, headers: dict[str, str]) -> Session:
    presence = (await db.execute(select(AgentPresence).where(
        AgentPresence.session_key == headers["x-octryx-session"]))).scalar_one()
    return await db.get(Session, presence.session_id)


def _observed(session: Session, tool: str, excerpt: str, *, is_error: bool = False,
              source: str = "mcp_server") -> ToolCall:
    return ToolCall(session_id=session.id, tool_name=tool, request_id=uuid.uuid4().hex,
                    parameters={"source": source, "input": {}}, status="error" if is_error else "success",
                    result={"is_error": is_error, "excerpt": excerpt})


@pytest.mark.asyncio
async def test_an_analysis_session_registers_pinned_to_its_item(client, db, monkeypatch):
    env = await _seat_env(db, monkeypatch)
    response, headers = await _register(client, db, env)
    assert response.status_code == 200 and response.json()["purpose"] == "work_item_analysis"
    assert response.json()["seat_credential"]
    metadata = (await _session(db, headers)).metadata_
    assert (metadata["gateway_purpose"], metadata["analysis_work_item_id"]) == ("work_item_analysis", env.item.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "reason"), [
    ("governed", "analysis_requires_seat"),
    ("runner_governed", "analysis_runner_not_seat"),
    ("no_key", "analysis_work_item_required"),
    ("unknown_key", "analysis_work_item_not_found"),
    ("purpose", "purpose_invalid"),
    ("seat_forbidden", "seat_mode_forbidden"),
])
async def test_an_analysis_session_is_refused_with_a_fixed_reason(client, db, monkeypatch, case, reason):
    settings = {"model_policy": f"{POLICY}@1"} if case == "runner_governed" else None
    config = {**SEAT_CONFIG, "agent_gateway_policy": {"seat_mode": "forbidden"}} if case == "seat_forbidden" else None
    env = await _seat_env(db, monkeypatch, settings=settings, config=config)
    response, headers = await _register(
        client, db, env, profile="governed" if case == "governed" else "seat",
        key={"no_key": "", "unknown_key": "INC-NOPE"}.get(case), purpose="coding" if case == "purpose" else
        "work_item_analysis")
    assert response.status_code == 403 and response.json()["reason"] == reason
    assert (await db.execute(select(AgentPresence).where(
        AgentPresence.session_key == headers["x-octryx-session"]))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_a_key_two_sources_share_is_refused_instead_of_pinning_one(client, db, monkeypatch):
    env = await _seat_env(db, monkeypatch)
    db.add(WorkItem(id=str(uuid.uuid4()), project_id=env.workspace_id, source_type=env.item.source_type,
                    source_instance="second-instance", source_key=env.item.source_key, title="Other item"))
    await db.commit()
    response, headers = await _register(client, db, env)
    assert response.status_code == 403 and response.json()["reason"] == "analysis_work_item_ambiguous"
    assert (await db.execute(select(AgentPresence).where(
        AgentPresence.session_key == headers["x-octryx-session"]))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_only_the_analysis_tools_pass_the_pre_tool_use_check(client, db, monkeypatch):
    env = await _seat_env(db, monkeypatch)
    _, headers = await _register(client, db, env)

    async def check(tool: str, tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await client.post(TOOL_CHECK, headers=headers, json=_pre_tool_use(tool, tool_input or {}))
        return response.json()

    for allowed in (SEARCH, "mcp__octryx-knowledge__knowledge_read",
                    "mcp__octryx-knowledge__work_item_context",
                    "mcp__octryx-knowledge__get_servicenow_record",
                    "mcp__octryx-knowledge__work_item_analysis_submit"):
        assert (await check(allowed))["decision"] == "allow", allowed
    for denied in ("Bash", "Read", "Edit", "WebFetch", "mcp__octryx-knowledge__work_item_note",
                   "mcp__octryx-knowledge__add_jira_comment", "mcp__other__knowledge_search"):
        answer = await check(denied, {"command": "ls"} if denied == "Bash" else {"file_path": "README.md"})
        assert (answer["decision"], answer["reason"]) == ("deny", "analysis_tool_not_allowed"), denied


@pytest.mark.asyncio
async def test_a_normal_seat_session_keeps_its_tools(client, db, monkeypatch):
    env = await _seat_env(db, monkeypatch)
    response, headers = await _register(client, db, env, purpose=None)
    assert response.status_code == 200 and "purpose" not in response.json()
    answer = (await client.post(TOOL_CHECK, headers=headers, json=_pre_tool_use("Bash", {"command": "ls"}))).json()
    assert answer["decision"] == "allow"


async def _registered(client, db, monkeypatch, **options):
    env = await _seat_env(db, monkeypatch, **options)
    _, headers = await _register(client, db, env)
    session = await _session(db, headers)
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_id == session.id))).scalar_one()
    presence.model = "claude-opus-5-5"
    await db.commit()
    return env, headers["x-octryx-session"], session


async def _submit(db, env, key: str | None, value: Any) -> dict[str, Any]:
    return await submit_seat_analysis(db, user=env.user, scope=_scope(env.workspace_id), session_key=key,
                                      analysis=value)


@pytest.mark.asyncio
async def test_a_cited_seat_analysis_is_stored_like_a_governed_one(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    db.add(_observed(session, EVIDENCE, MANUAL_HIT))
    await db.commit()
    stored = await _submit(db, env, key, analysis())
    assert (stored["status"], stored["runner"], stored["model"], stored["stored"]) == (
        "succeeded", "seat", "claude-opus-5-5", True)
    assert stored["cost_usd"] == 0.0 and stored["analysis"]["evidence"][0]["verified"] is True
    row = await db.get(WorkItemAnalysis, stored["id"])
    assert (row.session_id, row.mode) == (session.id, "manual")
    item = await db.get(WorkItem, env.item.id)
    note = item.source_fields_json["platform_notes"][-1]
    assert (note["kind"], note["author_type"], note["analysis_id"]) == ("analysis", "agent", row.id)
    board = await db.get(AgentBoardMessage, stored["board_message_id"])
    assert board is not None and board.work_item_id == env.item.id
    again = await _submit(db, env, key, analysis(summary="A second opinion."))
    assert (again["id"], again["reused"]) == (row.id, True)


@pytest.mark.asyncio
async def test_an_uncited_or_invalid_analysis_is_refused_and_nothing_is_stored(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    # Only the server's own successful read tool runs count: another tool, a failed call, or a tool_result the
    # client sent to the model gateway (whatever its name) never cites.
    db.add_all([_observed(session, "work_item_note", MANUAL_HIT),
                _observed(session, "WebFetch", MANUAL_HIT), _observed(session, EVIDENCE, MANUAL_HIT, is_error=True),
                _observed(session, SEARCH, MANUAL_HIT, source="model_gateway"),
                _observed(session, EVIDENCE, MANUAL_HIT, source="model_gateway")])
    await db.commit()
    assert (await _submit(db, env, key, analysis()))["error_code"] == "analysis_uncited"
    assert (await _submit(db, env, key, "not json"))["error_code"] == "analysis_not_json"
    assert (await _submit(db, env, key, {"summary": "x"}))["error_code"] == "analysis_invalid"
    db.add(_observed(session, EVIDENCE, MANUAL_HIT))
    await db.commit()
    leaky = analysis(summary="Rotate the key ghp_" + "a" * 36)
    assert (await _submit(db, env, key, json.dumps(leaky)))["error_code"] == "secret_detected"
    rows = (await db.execute(select(WorkItemAnalysis).where(WorkItemAnalysis.work_item_id == env.item.id))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_only_the_callers_own_active_analysis_session_may_submit(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    db.add(_observed(session, EVIDENCE, MANUAL_HIT))
    await db.commit()
    assert (await _submit(db, env, None, analysis()))["error_code"] == "seat_analysis_session_required"
    assert (await _submit(db, env, str(uuid.uuid4()), analysis()))["error_code"] == "seat_analysis_session_required"
    other = await _seat_env(db, monkeypatch)
    stolen = await submit_seat_analysis(db, user=other.user, scope=_scope(env.workspace_id), session_key=key,
                                        analysis=analysis())
    assert stolen["error_code"] == "seat_analysis_session_required"
    _, plain_headers = await _register(client, db, env, purpose=None)
    plain = await _submit(db, env, plain_headers["x-octryx-session"], analysis())
    assert plain["error_code"] == "seat_analysis_session_required"
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one()
    presence.profile = "governed"
    await db.commit()
    assert (await _submit(db, env, key, analysis()))["error_code"] == "seat_analysis_session_required"
    presence.profile = "seat"
    presence.stopped_at = presence.registered_at
    await db.commit()
    assert (await _submit(db, env, key, analysis()))["error_code"] == "seat_analysis_session_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(("change", "code"), [
    ({"agent_gateway_policy": {"seat_mode": "forbidden"}}, "seat_mode_forbidden"),
    ({"data_policy": {"classification": "restricted"}}, "seat_classification_too_sensitive"),
    ({"work_item_analysis": {"model_policy": f"{POLICY}@1", "runner": "governed"}}, "analysis_runner_not_seat"),
])
async def test_a_workspace_that_no_longer_allows_seat_refuses_the_submit(client, db, monkeypatch, change, code):
    env, key, session = await _registered(client, db, monkeypatch)
    db.add(_observed(session, EVIDENCE, MANUAL_HIT))
    project = await db.get(Project, env.workspace_id)
    project.config = {**project.config, **change}
    await db.commit()
    assert (await _submit(db, env, key, analysis()))["error_code"] == code


@pytest.mark.asyncio
async def test_the_mcp_tool_submits_for_the_connections_session(client, db, monkeypatch):
    env, key, session = await _registered(client, db, monkeypatch)
    db.add(_observed(session, EVIDENCE, MANUAL_HIT))
    await db.commit()

    @asynccontextmanager
    async def same_db():
        yield db

    async def no_binding(db, *, grant_id, user_id):
        return None

    monkeypatch.setattr(tools, "async_session_factory", same_db)
    monkeypatch.setattr(tools, "mcp_client_name", lambda ctx: "octryx-claude")
    monkeypatch.setattr(tools, "_session_key", lambda ctx: key)
    monkeypatch.setattr("app.services.mcp_work_access.resolve_work_grant_binding", no_binding)
    server = FastMCP("t")
    tools.register_work_analysis_tools(server, lambda ctx: (env.user.id, None, None, ("work:manage",)))
    listed = {tool.name for tool in await server.list_tools()}
    assert {"work_item_analyze", "work_item_analysis_submit"} <= listed
    result = await server.call_tool("work_item_analysis_submit", {"analysis": analysis()})
    content = result[0] if isinstance(result, tuple) else result
    payload = json.loads(content[0].text)
    assert payload["status"] == "succeeded" and payload["runner"] == "seat"


@pytest.mark.asyncio
async def test_the_knowledge_mcp_server_registers_the_submit_tool():
    from app.services.mcp_knowledge_protocol import build_knowledge_mcp_server

    assert "work_item_analysis_submit" in set(build_knowledge_mcp_server().code_tool_descriptions())
