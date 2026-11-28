"""Worker paths outside the chat dispatch get the session, so named connections work there."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project
from app.services import connector_test_service
from app.services.admin.project.named_connection_service import save_named
from app.services.connector_test import cloud as cloud_tests
from app.services.connector_test import incident as incident_tests
from app.services.proactive_teams import reply_handler
from app.tools.connectors import aws_core, azure, gcp, gcp_core
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_seed_support import seed_workspace

JIRA = "https://jira.example.test"
FAKE_DEFAULT = "fake-default-token"
FAKE_OPS = "fake-ops-token"


class _Recorder:
    name = "add_jira_comment"

    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict, object]] = []

    async def execute(self, params: dict, context) -> dict:
        self.calls.append((params, dict(context.project_config), context.db))
        return {"ok": True}


async def _workspace_with_named_jira(db) -> str:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = {**(project.config or {}), "teams_reply_to_jira": True}
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, is_active=True, config={
        "jira_url": JIRA, "jira_auth_mode": "bearer_pat", "jira_token": FAKE_DEFAULT,
    }))
    await db.flush()
    await save_named(db, connector="jira", project_id=workspace_id, actor_id=None, payload={
        "name": "ops", "bound_scopes": ["OPS"], "jira_url": JIRA, "jira_auth_mode": "bearer_pat",
        "jira_token": FAKE_OPS,
    })
    return workspace_id


@pytest.mark.parametrize(("ticket", "token"), [("OPS-7", FAKE_OPS), ("RIVER-3", FAKE_DEFAULT)])
async def test_the_teams_reply_comments_on_the_connection_of_the_tickets_project(db, monkeypatch, ticket, token):
    workspace_id = await _workspace_with_named_jira(db)
    recorder = _Recorder()
    monkeypatch.setitem(TOOL_REGISTRY, "add_jira_comment", recorder)

    async def no_resume(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(reply_handler, "_resume_agent_session", no_resume)
    await reply_handler.process_proactive_reply(db, {
        "ticket_id": ticket, "session_id": "session-1", "answer": "It fails since Monday.",
        "project_id": workspace_id,
    })

    [(params, config, session)] = recorder.calls
    assert params["ticket_id"] == ticket and "It fails since Monday." in params["body"]
    assert "connection" not in params
    assert config["jira_url"] == JIRA and config["jira_token"] == token
    assert session is db


async def test_the_teams_reply_never_comments_on_a_ticket_no_connection_serves(db, monkeypatch) -> None:
    workspace_id = await _workspace_with_named_jira(db)
    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.tool_name == "jira", BuiltInToolConfig.project_id == workspace_id))).scalar_one()
    entry.config = {**entry.config, "jira_allowed_projects": ["OPS"]}
    await db.flush()
    recorder = _Recorder()
    monkeypatch.setitem(TOOL_REGISTRY, "add_jira_comment", recorder)

    async def no_resume(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(reply_handler, "_resume_agent_session", no_resume)
    await reply_handler.process_proactive_reply(db, {
        "ticket_id": "RIVER-3", "session_id": "session-1", "answer": "x", "project_id": workspace_id,
    })
    assert recorder.calls == []


async def test_connection_tests_with_a_tool_context_get_the_callers_session(monkeypatch) -> None:
    session = object()
    seen: dict[str, object] = {}

    async def aws_json(context, service, command):
        seen["aws"] = context.db
        return {}

    async def azure_token(context):
        seen["azure"] = context.db
        return "token"

    async def gcp_token(context):
        seen["gcp"] = context.db
        return "token"

    async def http_json(*args, **kwargs):
        return {}

    def use_kubectl(context) -> bool:
        seen["kubernetes"] = context.db
        return True

    async def run_kubectl(context, args, timeout_sec):
        return 0, "{}", ""

    monkeypatch.setattr(aws_core, "_aws_json", aws_json)
    monkeypatch.setattr(azure, "_azure_token", azure_token)
    monkeypatch.setattr(gcp_core, "_gcp_access_token", gcp_token)
    monkeypatch.setattr(azure, "_http_json", http_json)
    monkeypatch.setattr(gcp, "_http_json", http_json)
    monkeypatch.setattr(incident_tests, "_should_use_kubectl", use_kubectl)
    monkeypatch.setattr(incident_tests, "_run_kubectl", run_kubectl)
    assert cloud_tests and connector_test_service.SESSION_CONNECTOR_TESTS == {"kubernetes", "aws", "azure", "gcp"}
    configs = {"aws": {"aws_allowed_services": ["sts"]}, "azure": {"azure_subscription_ids": ["sub-1"]},
               "gcp": {"gcp_access_token": "x"}, "kubernetes": {"k8s_context": "risk"}}

    for tool, config in configs.items():
        result = await connector_test_service.run_connector_connection_test(tool, config, db=session)
        assert result["ok"] is True, (tool, result)
    assert seen == dict.fromkeys(configs, session)
    await connector_test_service.run_connector_connection_test("aws", configs["aws"])
    assert seen["aws"] is None
