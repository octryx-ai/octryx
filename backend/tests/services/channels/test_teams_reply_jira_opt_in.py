"""A reporter's Teams reply is never posted to Jira without the Workspace's explicit opt-in, nor when an
approval rule covers ``add_jira_comment`` (the inbound reply cannot wait for an approval)."""

from __future__ import annotations

from typing import Any

import pytest

from app.models import Project
from app.services.proactive_teams import reply_handler
from app.services.proactive_teams.jira_reply_policy import teams_reply_to_jira_decision
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_seed_support import seed_workspace


class _Recorder:
    name = "add_jira_comment"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, params: dict, context) -> dict:
        self.calls.append(params)
        return {"ok": True}


async def _reply(db, monkeypatch, config: dict[str, Any] | None,
                 answer: str = "It fails since Monday.") -> tuple[_Recorder, list[str], str | None]:
    workspace_id = await seed_workspace(db)
    project = await db.get(Project, workspace_id)
    project.config = config or {}
    await db.flush()
    recorder = _Recorder()
    monkeypatch.setitem(TOOL_REGISTRY, "add_jira_comment", recorder)
    resumed: list[str] = []

    async def resume(_db, session_id, ticket_id, answer) -> None:
        resumed.append(answer)

    monkeypatch.setattr(reply_handler, "_resume_agent_session", resume)
    message = await reply_handler.process_proactive_reply(db, {
        "ticket_id": "OPS-7", "session_id": "session-1", "answer": answer,
        "project_id": workspace_id,
    })
    return recorder, resumed, message


@pytest.mark.parametrize("config", [None, {"teams_reply_to_jira": False}, {"teams_reply_to_jira": "true"}])
async def test_no_jira_write_without_the_workspace_opt_in(db, monkeypatch, config):
    recorder, resumed, message = await _reply(db, monkeypatch, config)
    assert recorder.calls == []
    assert resumed == ["It fails since Monday."]
    assert "added to ticket **OPS-7**" not in message


@pytest.mark.parametrize("policy", [{"require_for_tools": ["add_jira_comment"]}, {"require_for_risks": ["write"]}])
async def test_no_jira_write_when_an_approval_rule_covers_the_comment(db, monkeypatch, policy):
    recorder, _resumed, _message = await _reply(db, monkeypatch, {"teams_reply_to_jira": True, "approval_policy": policy})
    assert recorder.calls == []


async def test_the_opted_in_workspace_gets_the_comment(db, monkeypatch):
    recorder, resumed, message = await _reply(db, monkeypatch, {"teams_reply_to_jira": True})
    [params] = recorder.calls
    assert params["ticket_id"] == "OPS-7" and "It fails since Monday." in params["body"]
    assert resumed == ["It fails since Monday."]
    assert "added to ticket **OPS-7**" in message


def test_the_decision_defaults_to_off():
    assert teams_reply_to_jira_decision(None).reason == "teams_reply_to_jira_disabled"
    assert teams_reply_to_jira_decision({"teams_reply_to_jira": True}).allowed is True
    denied = teams_reply_to_jira_decision({"teams_reply_to_jira": True, "approval_policy": {"require_for_risks": ["write"]}})
    assert (denied.allowed, denied.reason) == (False, "approval_required")


async def test_the_comment_runs_without_a_platform_role_and_never_carries_a_secret(db, monkeypatch):
    seen_roles: list[list[str]] = []
    original = _Recorder.execute

    async def recording(self, params, context):
        seen_roles.append(list(context.roles))
        return await original(self, params, context)

    monkeypatch.setattr(_Recorder, "execute", recording)
    recorder, _resumed, _message = await _reply(db, monkeypatch, {"teams_reply_to_jira": True})
    assert len(recorder.calls) == 1 and seen_roles == [[]]

    leaked, resumed, _message = await _reply(db, monkeypatch, {"teams_reply_to_jira": True},
                                             answer="token: ghp_" + "a" * 36)
    assert leaked.calls == [] and len(resumed) == 1
