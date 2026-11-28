"""The Workspace analysis settings, the REST routes and the ``work_item_analyze`` MCP tool."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.models import AuditLog, Project, Role, UserRole
from app.services import mcp_work_analysis_tools as tools
from app.services.work_item_analysis.settings import (
    AnalysisSettings,
    AnalysisSettingsError,
    merged_settings,
    normalize_settings,
    settings_from_config,
)
from tests.agent_gateway.seat_presence_support import _bearer
from tests.knowledge_evidence_seed_support import seed_member
from tests.work_item_analysis.support import POLICY, Scripted, analysis, final, run_options, seed_env, tool_call

SETTINGS = "/api/v1/secure-work/work-item-analysis-settings"
ITEMS = "/api/v1/secure-work/work-items"


def test_defaults_are_off_with_a_one_dollar_cap():
    settings, source = settings_from_config({})
    assert source == "default" and settings == AnalysisSettings()
    assert settings.as_dict() == {"model_policy": None, "cost_cap_usd": 1.0, "ask_reporter": False,
                                  "auto_analyze": {"servicenow_new_incidents": False, "jira_label": None},
                                  "runner": "governed", "max_output_tokens": 8192}


@pytest.mark.parametrize(("value", "code", "field"), [
    ({"surprise": 1}, "unknown_key", "work_item_analysis.surprise"),
    ({"auto_analyze": {"servicenow": True}}, "unknown_key", "work_item_analysis.auto_analyze.servicenow"),
    ({"cost_cap_usd": 0}, "out_of_range", "work_item_analysis.cost_cap_usd"),
    ({"cost_cap_usd": 51}, "out_of_range", "work_item_analysis.cost_cap_usd"),
    ({"cost_cap_usd": True}, "number_required", "work_item_analysis.cost_cap_usd"),
    ({"cost_cap_usd": "nan"}, "out_of_range", "work_item_analysis.cost_cap_usd"),
    ({"ask_reporter": "yes"}, "boolean_required", "work_item_analysis.ask_reporter"),
    ({"auto_analyze": {"jira_label": "two words"}}, "label_invalid", "work_item_analysis.auto_analyze.jira_label"),
    ({"auto_analyze": {"jira_label": ""}}, "label_invalid", "work_item_analysis.auto_analyze.jira_label"),
    ({"model_policy": "no-revision"}, "model_policy_ref_invalid", "work_item_analysis.model_policy"),
    ([], "object_required", "work_item_analysis"),
    ({"runner": "bedrock"}, "runner_invalid", "work_item_analysis.runner"),
    ({"runner": None}, "runner_invalid", "work_item_analysis.runner"),
    ({"max_output_tokens": 1023}, "out_of_range", "work_item_analysis.max_output_tokens"),
    ({"max_output_tokens": 32001}, "out_of_range", "work_item_analysis.max_output_tokens"),
    ({"max_output_tokens": "8192"}, "integer_required", "work_item_analysis.max_output_tokens"),
    ({"max_output_tokens": True}, "integer_required", "work_item_analysis.max_output_tokens"),
])
def test_invalid_settings_are_refused_with_a_code_and_field(value, code, field):
    with pytest.raises(AnalysisSettingsError) as refused:
        normalize_settings(value)
    assert (refused.value.code, refused.value.field) == (code, field)


def test_runner_and_output_bound_round_trip_at_their_limits():
    stored = normalize_settings({"runner": "seat", "max_output_tokens": 1024})
    settings, source = settings_from_config({"work_item_analysis": stored})
    assert (source, settings.runner, settings.max_output_tokens) == ("workspace", "seat", 1024)
    assert normalize_settings({"max_output_tokens": 32000})["max_output_tokens"] == 32000


def test_a_broken_stored_value_runs_nothing_and_a_patch_merges():
    settings, source = settings_from_config({"work_item_analysis": {"auto_analyze": {"jira_label": 7}}})
    assert (source, settings.jira_label) == ("invalid", None)
    current = AnalysisSettings(model_policy="p@1", jira_label="octryx")
    merged = merged_settings(current, {"auto_analyze": {"servicenow_new_incidents": True}, "ask_reporter": True})
    assert merged["auto_analyze"] == {"servicenow_new_incidents": True, "jira_label": "octryx"}
    assert merged["model_policy"] == "p@1" and merged["ask_reporter"] is True


@pytest.mark.asyncio
async def test_the_project_config_path_refuses_an_invalid_section(db):
    from app.services.admin.project.admin_project_config_service import apply_project_config_patch

    env_project = Project(id="p-settings", name="p-settings", config={}, is_active=True)
    db.add(env_project)
    await db.flush()
    with pytest.raises(HTTPException) as refused:
        await apply_project_config_patch(db, project=env_project, patch={"work_item_analysis": {"cost_cap_usd": 99}},
                                         actor_user_id="admin")
    assert refused.value.status_code == 400
    assert refused.value.detail["errors"][0]["field"] == "work_item_analysis.cost_cap_usd"


@pytest.mark.asyncio
async def test_settings_rest_reads_for_members_and_writes_for_admins(client, db, monkeypatch):
    env = await seed_env(db, monkeypatch, settings={"model_policy": f"{POLICY}@1"})
    member = await seed_member(db, workspace_id=env.workspace_id, role="member")
    outsider = await seed_member(db, workspace_id=(await seed_env(db, monkeypatch)).workspace_id, role="owner")
    await db.commit()
    path = f"{SETTINGS}/{env.workspace_id}"
    read = await client.get(path, headers=await _bearer(member))
    assert read.status_code == 200
    assert read.json() == {"project_id": env.workspace_id, "model_policy": f"{POLICY}@1", "cost_cap_usd": 1.0,
                                "auto_analyze": {"servicenow_new_incidents": False, "jira_label": None},
                                "ask_reporter": False, "runner": "governed", "max_output_tokens": 8192,
                                "source": "workspace", "can_edit": False}
    assert (await client.put(path, json={"ask_reporter": True}, headers=await _bearer(member))).status_code == 403
    assert (await client.get(path, headers=await _bearer(outsider))).status_code == 404
    bad = await client.put(path, json={"cost_cap_usd": -1}, headers=await _bearer(env.user.id))
    assert bad.status_code == 422 and bad.json()["detail"]["errors"][0]["code"] == "out_of_range"
    saved = await client.put(path, json={"auto_analyze": {"servicenow_new_incidents": True, "jira_label": "octryx"},
                                         "ask_reporter": True}, headers=await _bearer(env.user.id))
    assert saved.status_code == 200 and saved.json()["model_policy"] == f"{POLICY}@1"
    assert saved.json()["auto_analyze"] == {"servicenow_new_incidents": True, "jira_label": "octryx"}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "work_item_analysis.settings_updated"))
             ).scalars().all()
    assert audit and audit[-1].details["after"]["ask_reporter"] is True


async def _operator(db, user_id: str) -> None:
    role = (await db.execute(select(Role).where(Role.name == "operation"))).scalar_one_or_none()
    if role is None:
        role = Role(name="operation", description="operation")
        db.add(role)
        await db.flush()
    db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.commit()


@pytest.mark.asyncio
async def test_the_analyze_route_runs_for_operators_in_scope(client, db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    seen = []

    async def analyze(db, *, item, user, mode):
        seen.append((item.id, user.id, mode))
        return {"id": "a1", "status": "succeeded"}

    monkeypatch.setattr("app.api.routes.workflows.work_item_analysis.analyze_work_item", analyze)
    path = f"{ITEMS}/{env.item.id}/analyze"
    assert (await client.post(path, json={}, headers=await _bearer(env.user.id))).status_code == 403
    await _operator(db, env.user.id)
    started = await client.post(path, json={}, headers=await _bearer(env.user.id))
    assert started.status_code == 200 and seen == [(env.item.id, env.user.id, "manual")]
    other = await seed_env(db, monkeypatch)
    out_of_scope = await client.post(f"{ITEMS}/{other.item.id}/analyze", json={}, headers=await _bearer(env.user.id))
    assert out_of_scope.status_code == 404 and len(seen) == 1


@pytest.mark.asyncio
async def test_the_latest_analysis_and_the_history_are_readable(client, db, monkeypatch):
    from app.services.work_item_analysis.runner import analyze_work_item

    env = await seed_env(db, monkeypatch)
    await _operator(db, env.user.id)
    headers = await _bearer(env.user.id)
    # No analysis yet is an ordinary state (200), not a 404: the item panel asks on every open.
    missing = await client.get(f"{ITEMS}/{env.item.id}/analysis", headers=headers)
    assert missing.status_code == 200
    assert missing.json()["status"] == "none" and missing.json()["analysis"] is None
    assert missing.json()["work_item_id"] == env.item.id
    unknown = await client.get(f"{ITEMS}/no-such-item/analysis", headers=headers)
    assert unknown.status_code == 404
    search = tool_call("knowledge_search", {"query": "TLS"})
    done = await analyze_work_item(db, item=env.item, user=env.user,
                                   **run_options(Scripted([search, final(analysis())])))
    latest = (await client.get(f"{ITEMS}/{env.item.id}/analysis", headers=headers)).json()
    assert latest["id"] == done["id"] and latest["analysis"]["evidence"][0]["verified"] is True
    history = (await client.get(f"{ITEMS}/{env.item.id}/analyses", headers=headers)).json()["items"]
    assert [row["id"] for row in history] == [done["id"]]


async def _mcp(db, monkeypatch, user_id: str) -> FastMCP:
    @asynccontextmanager
    async def session():
        yield db

    async def no_binding(db, *, grant_id, user_id):
        return None

    monkeypatch.setattr(tools, "async_session_factory", session)
    monkeypatch.setattr(tools, "mcp_client_name", lambda ctx: "octryx-claude")
    monkeypatch.setattr("app.services.mcp_work_access.resolve_work_grant_binding", no_binding)
    server = FastMCP("t")
    tools.register_work_analysis_tools(server, lambda ctx: (user_id, None, None, ("work:manage",)))
    return server


@pytest.mark.asyncio
async def test_the_mcp_tool_analyses_an_item_the_grant_reaches(db, monkeypatch):
    env = await seed_env(db, monkeypatch)
    calls = []

    async def analyze(db, *, item, user, mode):
        calls.append((item.id, mode))
        return {"id": "a1", "status": "succeeded", "content_is_data": "x"}

    monkeypatch.setattr(tools, "analyze_work_item", analyze)
    server = await _mcp(db, monkeypatch, env.user.id)
    result = await server.call_tool("work_item_analyze", {"work_item_id": env.item.source_key})
    content = result[0] if isinstance(result, tuple) else result
    assert json.loads(content[0].text)["status"] == "succeeded" and calls == [(env.item.id, "manual")]
    other = await seed_env(db, monkeypatch)
    with pytest.raises(Exception, match="not found"):
        await server.call_tool("work_item_analyze", {"work_item_id": other.item.id})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_knowledge_mcp_server_registers_work_item_analyze():
    from app.services.mcp_knowledge_protocol import build_knowledge_mcp_server

    names = set(build_knowledge_mcp_server().code_tool_descriptions())
    assert "work_item_analyze" in names


def test_cost_values_round_trip_as_decimals():
    settings, _ = settings_from_config({"work_item_analysis": {"cost_cap_usd": "2.5"}})
    assert settings.cost_cap_usd == Decimal("2.5")


@pytest.mark.asyncio
async def test_a_proposal_not_sent_stays_proposed_and_can_be_sent_later(client, db, monkeypatch):
    from app.models import WorkItemAnalysis

    env = await seed_env(db, monkeypatch)
    await _operator(db, env.user.id)
    proposed = {"state": "proposed", "reason": "awaits_person", "questions": 1}
    row = WorkItemAnalysis(project_id=env.workspace_id, work_item_id=env.item.id, item_version="v", template="t",
                           mode="auto", status="succeeded", requested_by=env.user.id, cost_usd=Decimal("0"),
                           tokens_in=0, tokens_out=0, analysis_json={"open_questions": ["When?"]},
                           reporter_question=dict(proposed))
    db.add(row)
    await db.commit()
    attempts = iter([{"state": "skipped", "reason": "ask_reporter_off"}, {"state": "failed", "reason": "jira_http_500"},
                     {"state": "posted", "comment_id": "1", "questions": 1}])

    async def post(db, *, item, analysis, ask, person_id):
        return next(attempts)

    monkeypatch.setattr("app.api.routes.workflows.work_item_analysis.post_proposed_questions", post)
    path = f"{ITEMS}/{env.item.id}/analyses/{row.id}/ask-reporter"
    headers = await _bearer(env.user.id)
    for expected in ("skipped", "failed"):
        answer = (await client.post(path, headers=headers)).json()
        assert answer["sent"] is False and answer["attempt"]["state"] == expected
        assert answer["reporter_question"] == proposed
    sent = (await client.post(path, headers=headers)).json()
    assert sent["sent"] is True and sent["reporter_question"]["state"] == "posted"
