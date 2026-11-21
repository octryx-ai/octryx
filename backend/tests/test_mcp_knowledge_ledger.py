"""The Knowledge MCP on the governed ledger.

Contract tests over the real ledger and the in-memory object store and Evidence index doubles:

- ``knowledge_search`` keeps its name for external CLIs and answers from the governed Knowledge
  ledger, scoped to the connection's Workspace, with source title, section and an openable source
  link on every passage, and no other read path;
- ``episode_summary`` writes a session summary as a governed source revision: refused explicitly
  until the Workspace accepts episodes, redacted, idempotent per (session, digest), owing its
  projection through the outbox, and searchable afterwards with a citation that links to the session;
- platform sessions return an episode through the Workspace API.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import get_settings
from app.models import AuditLog, Session, ToolCall
from app.models.project.knowledge_evidence import KnowledgeProjectionOutboxEntry
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.episodes.policy import set_episodes_accepted
from app.services.knowledge.ingestion.text_ingest import ingest_text_source
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.runtime import set_evidence_runtime
from app.services.mcp_governed_knowledge import McpCaller, run_governed_mcp_tool
from app.services.mcp_knowledge_episode import run_episode_summary
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_evidence_text_support import unfenced
from tests.mcp_knowledge_support import _outbox_states_for_revision, _span_texts_for_revision

ORIGIN = "https://octryx.example.test"
RUNBOOK = "https://confluence.example.test/wiki/spaces/RIVER/pages/7/Failover"
READ_WRITE = ("knowledge:read", "knowledge:write")


@pytest.fixture
def evidence_runtime():
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def public_origin(monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", ORIGIN)


def _caller(user_id: str, **overrides) -> McpCaller:
    values = {
        "user_id": user_id,
        "grant_id": f"grant-{user_id[:8]}",
        "scopes": READ_WRITE,
        "client_name": "claude-code",
    }
    values.update(overrides)
    return McpCaller(**values)


async def _workspace_with_source(db, runtime, evidence_index, *, text: bytes, source_url: str | None = RUNBOOK):
    workspace_id = await seed_workspace(db)
    author_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, author_id), workspace_id=workspace_id)
    await ingest_text_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="failover-runbook",
        display_title="Failover Runbook",
        declared_media_type="text/markdown",
        data=text,
        created_by=author_id,
        source_url=source_url,
    )
    await EvidenceProjector(runtime).project_once(db, worker_id="test")
    return workspace_id, author_id


async def test_knowledge_search_answers_from_the_ledger_with_source_links_in_the_connection_workspace(
    db, evidence_runtime
):
    runtime, evidence_index = evidence_runtime
    workspace_id, _ = await _workspace_with_source(
        db, runtime, evidence_index, text=b"# Drill\n\nThe failover drill runs from Geneva every quarter.\n"
    )
    other_id, _ = await _workspace_with_source(db, runtime, evidence_index, text=b"The failover drill runs from Lugano.\n")
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    member = _caller(member_id, workspace_header=workspace_id)

    # Extra arguments (project_id, layers) are ignored: the scope is the connection's.
    result = await run_governed_mcp_tool(
        db,
        caller=member,
        tool_name="knowledge_search",
        arguments={"query": "failover drill", "project_id": other_id, "layers": ["gold"]},
    )

    assert (result["state"], result["workspace_id"]) == ("ok", workspace_id)
    # The passage text reaches the coding agent fenced as untrusted data (knowledge_fence); its words are inside.
    assert [unfenced(item["text"]).split("\n")[-1] for item in result["evidence"]] == [
        "The failover drill runs from Geneva every quarter."
    ]
    passage = result["evidence"][0]
    assert (passage["source_title"], passage["section"], passage["source_url"]) == (
        "Failover Runbook",
        "Drill",
        RUNBOOK,
    )
    assert passage["cite_as"] == f"[Failover Runbook § Drill]({RUNBOOK})"
    assert "legacy-failover" not in json.dumps(result) and "changes" not in result

    # Typed change facts are only asked for with one product and a version; here the graph is not
    # configured, which is reported as its own state and does not fail the search.
    narrowed = await run_governed_mcp_tool(
        db, caller=member, tool_name="knowledge_search", arguments={"query": "failover", "products": ["acme-orders"]}
    )
    assert narrowed["state"] == "ok" and "changes" not in narrowed
    with_version = await run_governed_mcp_tool(
        db,
        caller=member,
        tool_name="knowledge_search",
        arguments={"query": "failover", "products": ["acme-orders"], "version": "2.0"},
    )
    assert with_version["state"] == "ok" and with_version["changes"]["state"] == "needs_configuration"

    # Authorization: the Workspace comes from the grant binding or the header, never from arguments.
    def search(caller):
        return run_governed_mcp_tool(db, caller=caller, tool_name="knowledge_search", arguments={"query": "failover"})

    assert (await search(_caller(member_id)))["state"] == "needs_configuration"
    assert (await search(_caller(member_id, bound_project_ids=(workspace_id,))))["state"] == "ok"
    assert (await search(_caller(member_id, workspace_header=other_id)))["state"] == "not_found"
    bound_elsewhere = _caller(member_id, bound_project_ids=(other_id,), workspace_header=workspace_id)
    assert (await search(bound_elsewhere))["state"] == "not_found"
    no_read = _caller(member_id, workspace_header=workspace_id, scopes=("tasks:read",))
    assert (await search(no_read))["state"] == "denied"


async def test_the_legacy_knowledge_search_read_path_is_gone(db):
    from mcp.server.fastmcp import FastMCP

    from app.services import mcp_knowledge
    from app.services.mcp_knowledge_ledger_tools import register_knowledge_ledger_tools

    assert not hasattr(mcp_knowledge, "mcp_knowledge_query")
    with pytest.raises(HTTPException) as refused:
        await mcp_knowledge.load_mcp_knowledge_tool(
            db, user=None, bound_project_ids=None, tool_name="knowledge_search", arguments={}
        )
    assert refused.value.status_code in {400, 404}

    server = FastMCP("test")
    register_knowledge_ledger_tools(server, lambda ctx: ("u", None, None, ()))
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools) == {"knowledge_search", "jira_release_status", "episode_summary"}
    for tool in tools.values():
        assert not {"project_id", "workspace_id", "user_id", "session_id"} & set(tool.inputSchema["properties"])
    assert "query" in tools["knowledge_search"].inputSchema["required"]


EPISODE_SUMMARY = (
    "Decided to pin the Zurich failover target to cluster blue.\n\n"
    "Deploy with password=Hunter2Hunter2 and token ghp_abcdefghijklmnopqrstuvwxyz0123 (rotate them)."
)


async def _assert_episode_refusals(db, episode, sessions, *, workspace_id, member_id, viewer_id):
    # Off by default: an explicit state, and nothing is created before the refusal.
    member = _caller(member_id, workspace_header=workspace_id)
    refused = await episode(member)
    assert (refused["state"], refused["reason"]) == ("needs_configuration", "episodes_disabled")
    before = await sessions()
    await set_episodes_accepted(db, workspace_id, accepted=True)
    assert (await episode(_caller(member_id, workspace_header=workspace_id, scopes=("knowledge:read",))))[
        "state"
    ] == "denied"
    assert (await episode(_caller(viewer_id, workspace_header=workspace_id)))["reason"] == "role_required"
    assert (await episode(_caller(member_id)))["state"] == "needs_configuration"
    assert (await episode(member, client_session_id="../x"))["reason"] == "invalid_session"
    assert (await episode(member, summary="x" * 8001))["state"] == "limit_exceeded"
    assert await sessions() == before


async def _assert_recorded_episode_session(db, recorded, *, member_id, workspace_id) -> str:
    """Checks the session the episode created and returns its openable link."""
    session = await db.get(Session, recorded["session_id"])
    assert (session.user_id, session.project_id, session.agent_type) == (member_id, workspace_id, "external_agent")
    assert session.metadata_["client_session_id"] == "claude-code-7f3a"
    link = f"{ORIGIN}/chat?session_id={session.id}"
    assert recorded["source_url"] == link
    assert recorded["source_key"] == f"session-episode.{session.id}"
    return link


async def _search_episode_hits(db, runtime, *, author_id, workspace_id, link) -> list[dict]:
    await EvidenceProjector(runtime).project_once(db, worker_id="test")
    found = await run_governed_mcp_tool(
        db,
        caller=_caller(author_id, workspace_header=workspace_id),
        tool_name="knowledge_search",
        arguments={"query": "Zurich failover cluster"},
    )
    return [item for item in unfenced(found["evidence"]) if item["source_url"] == link]


async def test_episode_summary_is_governed_redacted_idempotent_and_becomes_cited_evidence(
    db, evidence_runtime, public_origin
):
    runtime, evidence_index = evidence_runtime
    workspace_id, author_id = await _workspace_with_source(db, runtime, evidence_index, text=b"Unrelated runbook text.\n")
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    viewer_id = await seed_member(db, workspace_id=workspace_id, role="viewer")
    member = _caller(member_id, workspace_header=workspace_id)
    arguments = {"summary": EPISODE_SUMMARY, "client_session_id": "claude-code-7f3a", "title": "Failover pinning"}

    async def episode(caller, **overrides):
        return await run_episode_summary(db, caller=caller, arguments={**arguments, **overrides})

    async def sessions() -> int:
        return (
            await db.execute(select(func.count()).select_from(Session).where(Session.user_id == member_id))
        ).scalar()

    await _assert_episode_refusals(
        db, episode, sessions, workspace_id=workspace_id, member_id=member_id, viewer_id=viewer_id
    )

    recorded = await episode(member)
    assert (recorded["state"], recorded["redactions"], recorded["projection"]) == ("recorded", 2, "pending")
    link = await _assert_recorded_episode_session(db, recorded, member_id=member_id, workspace_id=workspace_id)
    outbox = await _outbox_states_for_revision(db, recorded["revision_id"])
    assert outbox == ["pending"]

    # Same session, same summary: the revision that exists, no new obligation, no second session.
    again = await episode(member)
    assert (again["state"], again["revision_id"], again["session_id"]) == (
        "duplicate",
        recorded["revision_id"],
        recorded["session_id"],
    )
    assert (await db.execute(select(func.count()).select_from(KnowledgeProjectionOutboxEntry))).scalar() == 2

    search_scope = {"author_id": author_id, "workspace_id": workspace_id, "link": link}
    hits = await _search_episode_hits(db, runtime, **search_scope)
    assert "cluster blue" in hits[0]["text"]
    spans = await _span_texts_for_revision(db, recorded["revision_id"])
    stored_text = " ".join(spans)
    assert "Hunter2" not in stored_text and "ghp_abcdef" not in stored_text and stored_text.count("[redacted]") == 2
    assert hits[0]["cite_as"] == f"[Session episode (claude-code): Failover pinning]({link})"

    # A changed summary of the same session is its next revision and replaces the previous one.
    changed = await episode(member, summary="Decided to pin the Zurich failover target to cluster green.")
    assert (changed["state"], changed["revision"], changed["session_id"]) == ("recorded", 2, recorded["session_id"])
    hits = await _search_episode_hits(db, runtime, **search_scope)
    assert [hit["text"] for hit in hits] == ["Decided to pin the Zurich failover target to cluster green."]

    # Neither the activity rows nor the audit log keep a copy of the summary.
    activity = (await db.execute(select(ToolCall.parameters))).scalars().all()
    audits = (await db.execute(select(AuditLog.details).where(AuditLog.user_id == member_id))).scalars().all()
    stored = json.dumps([*activity, *audits])
    assert "cluster blue" not in stored and "Hunter2" not in stored


async def test_a_platform_session_returns_its_episode_through_the_workspace_api(
    client, db, auth_headers, evidence_runtime, public_origin
):
    from app.models import User

    runtime, evidence_index = evidence_runtime
    workspace_id = await seed_workspace(db)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    own = Session(user_id=admin.id, project_id=workspace_id, agent_type="chat")
    foreign_member = await seed_member(db, workspace_id=workspace_id, role="member")
    foreign = Session(user_id=foreign_member, project_id=workspace_id, agent_type="chat")
    db.add_all([own, foreign])
    await db.commit()
    base = f"/api/v1/workspaces/{workspace_id}/knowledge/episodes"
    body = {"session_id": own.id, "summary": "The release freeze starts on Friday."}

    assert (await client.post(base, json=body, headers=auth_headers)).status_code == 409
    settings = await client.put(f"{base}/settings", json={"accept_session_episodes": True}, headers=auth_headers)
    assert settings.json()["accept_session_episodes"] is True

    recorded = await client.post(base, json=body, headers=auth_headers)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["state"] == "recorded"
    assert recorded.json()["source_url"] == f"{ORIGIN}/chat?session_id={own.id}"
    assert recorded.json()["cite_as"].startswith("[Session episode (platform): ")
    # Another user's session is indistinguishable from an unknown one.
    other = await client.post(base, json={**body, "session_id": foreign.id}, headers=auth_headers)
    assert other.status_code == 404
