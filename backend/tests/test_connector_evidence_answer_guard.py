"""End to end over run_agent: a Jira-stub answer with a browse link passes the answer evidence guard, and without links it is delivered with a sources note."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import BuiltInToolConfig, Project, Session, TurnTrace, User
from app.services.answer_evidence.record import read_answer_evidence
from tests.connector_evidence_fields_support import JIRA, _issue
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

# --- end to end: a Jira-stub answer through the answer evidence guard --------------------------------


async def _jira_chat_session(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()), name=f"e1-jira-{uuid.uuid4().hex[:6]}", config={"enabled_connectors": ["jira"]}, is_active=True
    )
    db.add(project)
    await db.flush()
    db.add(
        BuiltInToolConfig(
            id=str(uuid.uuid4()),
            tool_name="jira",
            project_id=project.id,
            config={"jira_url": JIRA, "jira_email": "stub@example.test", "jira_allowed_projects": ["OPS"]},
            is_active=True,
        )
    )
    session = Session(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()
    return admin, project, session


def _jira_turn(monkeypatch, answers: list[str]) -> list[list[dict]]:
    async def fake_get(client, jira_url, path, **_kwargs):
        assert jira_url == JIRA
        return {"issues": [_issue("OPS-2", "Failover drill blocked")], "total": 1}, "2"

    replies = [
        {
            "content": "",
            "tool_calls": [
                {"id": "c1", "function": {"name": "search_jira_tickets", "arguments": '{"jql": "project = OPS"}'}}
            ],
        },
        *({"content": answer} for answer in answers),
    ]
    seen: list[list[dict]] = []

    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

    async def fake_chat(*, runtimes, messages, tools, **_kwargs):
        seen.append(list(messages))
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return {"tool_calls": None, "model": "anthropic.claude-sonnet-4-5", **replies.pop(0), "usage": usage}, runtimes[0]

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_get)
    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)
    return seen


async def _run(db, admin, project, session) -> tuple[list[str], list[str]]:
    contents: list[str] = []
    async for event in run_agent(
        session_id=session.id, user_message="Which OPS ticket blocks the failover?", user_id=admin.id,
        project_id=project.id, agent_type="chat", db=db,
    ):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    traces = (
        await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at))
    ).scalars().all()
    decisions = [record["evidence_guard"] for trace in traces if (record := read_answer_evidence(trace.context_snapshot_json))]
    return contents, decisions


CITED = f"The failover drill is blocked by [OPS-2: Failover drill blocked]({JIRA}/browse/OPS-2), which is still open.\n"


UNCITED = "The failover drill is blocked by OPS-2, which is still open with high priority.\n"


@pytest.mark.asyncio
async def test_a_jira_stub_answer_with_a_browse_link_passes_the_guard(db, monkeypatch) -> None:
    admin, project, session = await _jira_chat_session(db)
    seen = _jira_turn(monkeypatch, [CITED])

    contents, decisions = await _run(db, admin, project, session)

    tool_message = next(m for m in seen[1] if m.get("role") == "tool")
    assert f"{JIRA}/browse/OPS-2" in str(tool_message.get("content")), "the model saw the source link"
    assert contents[-1] == CITED and decisions[-1] == "passed"


@pytest.mark.asyncio
async def test_the_same_jira_answer_without_links_is_delivered_with_its_sources_note(db, monkeypatch) -> None:
    """Never withheld: after the reminder the answer comes with the ticket link it missed."""
    admin, project, session = await _jira_chat_session(db)
    _jira_turn(monkeypatch, [UNCITED, UNCITED])

    contents, decisions = await _run(db, admin, project, session)

    assert "withheld" not in contents[-1] and contents[-1].startswith(UNCITED.rstrip())
    assert "No source linked" in contents[-1] and f"{JIRA}/browse/OPS-2" in contents[-1]
    assert decisions[-2:] == ["reminded", "marked"]
