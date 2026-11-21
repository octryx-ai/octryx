"""Session episodes from platform chat turns (open point K1).

Contract tests over the real ledger writer and an in-memory evidence runtime:

- **Automatic capture** at the end of a platform turn is opt-in twice (``accept_session_episodes`` and
  ``capture_platform_turns``), sees only user-visible text (never tool payloads), redacts before the
  model call and before the write, writes through the governed writer, runs once per answer,
  deduplicates by digest, and never raises. It is wired into the same post-turn hook as the Memory
  capture, and its model call is a registered, admitted dispatch owner.
- **The settings API** switches the sub-setting on its own and audits old/new booleans only.
- **The chat tool** ``knowledge_episode_summary`` uses the same writer, is refused to sub-agents and
  foreign sessions, and is classified as a built-in internal write that needs ``change``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import AuditLog, Message, Session
from app.models.project.knowledge_evidence import (
    KnowledgeEvidenceSpan,
    KnowledgeProjectionOutboxEntry,
    KnowledgeSourceRevision,
)
from app.services.knowledge.episodes import turn_capture
from app.services.knowledge.episodes.policy import POLICY_AUDIT_ACTION, set_episode_policy
from app.services.knowledge.episodes.turn_capture import capture_turn_episode, run_turn_episode_capture
from app.services.knowledge.memory.capture_model import CaptureModelUnavailableError
from app.services.knowledge.runtime import set_evidence_runtime
from app.services.model_gateway.dispatch_owners import DISPATCH_OWNERS
from app.services.session import turn_follow_up
from app.time_utils import utc_now
from app.tools.capability_requirements import tool_required_capability
from app.tools.definitions import get_tool_definition_metadata
from app.tools.definitions.write_risk import BUILT_IN_INTERNAL_WRITE_DEFINITION_NAMES
from app.tools.knowledge_evidence.episode_summary import KnowledgeEpisodeSummaryTool
from app.tools.registry import TOOL_REGISTRY
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace, tool_context

ORIGIN = "https://octryx.example.test"
RUNBOOK = "https://confluence.example.test/wiki/spaces/RIVER/pages/7/Failover"
TOOL_MARKER = "RAW-TOOL-PAYLOAD-7731"
SECRET = "ghp_abcdefghijklmnopqrstuvwxyz0123"


@pytest.fixture
def evidence_runtime():
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def public_origin(monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", ORIGIN)


class FakeSummaryModel:
    """Records every prompt and answers the given summary; never touches a provider."""

    def __init__(self, summary: str, title: str = "Failover pinning") -> None:
        self.summary = summary
        self.title = title
        self.prompts: list[str] = []

    async def __call__(self, db, *, project_id: str):
        return self

    async def json(self, *, system: str, user: str) -> dict:
        self.prompts.append(user)
        return {"title": self.title, "summary": self.summary}


async def _session_with_turn(db, *, workspace_id: str, user_id: str, parent_id: str | None = None) -> str:
    session = Session(user_id=user_id, project_id=workspace_id, agent_type="chat", parent_session_id=parent_id)
    db.add(session)
    await db.flush()
    await _turn(
        db, session.id, question="Which cluster is the Zurich failover target?", at=utc_now() - timedelta(minutes=5)
    )
    return session.id


async def _turn(db, session_id: str, *, question: str, at, answer: str | None = None) -> None:
    answer = answer or (
        f"The Zurich failover target is cluster blue [Failover Runbook § Drill]({RUNBOOK}). "
        f"Rotate the deploy token {SECRET} afterwards."
    )
    db.add_all(
        [
            Message(session_id=session_id, role="user", content=question, created_at=at),
            Message(session_id=session_id, role="tool", content=TOOL_MARKER, created_at=at + timedelta(seconds=1)),
            Message(
                session_id=session_id,
                role="assistant",
                content=answer,
                tool_results=[{"output": TOOL_MARKER}],
                created_at=at + timedelta(seconds=2),
            ),
        ]
    )
    await db.flush()


async def _revisions(db, workspace_id: str) -> int:
    statement = (
        select(func.count())
        .select_from(KnowledgeSourceRevision)
        .where(KnowledgeSourceRevision.project_id == workspace_id)
    )
    return int((await db.execute(statement)).scalar_one())


async def test_turn_capture_is_opt_in_redacted_once_per_answer_and_deduplicated(
    db, evidence_runtime, public_origin
) -> None:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    session_id = await _session_with_turn(db, workspace_id=workspace_id, user_id=member_id)
    summary = f"Zurich failover target: cluster blue. Deploy token {SECRET}.\n\nSources: [Failover Runbook]({RUNBOOK})"
    model = FakeSummaryModel(summary)

    async def capture():
        return await capture_turn_episode(db, session_id=session_id, model_factory=model)

    # Off by default, and each switch alone is off: no model call, nothing written.
    assert (await capture()).reason == "disabled"
    await set_episode_policy(db, workspace_id, accepted=True)
    assert (await capture()).reason == "disabled"
    await set_episode_policy(db, workspace_id, accepted=False, capture_platform_turns=True)
    assert (await capture()).reason == "disabled"
    assert model.prompts == [] and await _revisions(db, workspace_id) == 0

    await set_episode_policy(db, workspace_id, accepted=True)
    recorded = await capture()
    assert (recorded.reason, recorded.revision) == ("recorded", 1)
    # The model saw the question, the answer and its cited source; never a tool payload or the secret.
    prompt = model.prompts[0]
    assert (
        "Which cluster is the Zurich failover target?" in prompt
        and f"- [Failover Runbook § Drill]({RUNBOOK})" in prompt
    )
    assert TOOL_MARKER not in prompt and SECRET not in prompt
    stored = " ".join(
        (await db.execute(select(KnowledgeEvidenceSpan.text).where(KnowledgeEvidenceSpan.project_id == workspace_id)))
        .scalars()
        .all()
    )
    assert "cluster blue" in stored and SECRET not in stored and TOOL_MARKER not in stored

    # Once per answer: the same turn is not summarized again.
    assert (await capture()).reason == "already_captured" and len(model.prompts) == 1

    # A later turn updates the session's summary: the model gets the current one; an unchanged
    # answer is a duplicate by digest and owes no new projection.
    await _turn(db, session_id, question="And the Geneva target?", at=utc_now() + timedelta(seconds=5))
    outbox_before = (await db.execute(select(func.count()).select_from(KnowledgeProjectionOutboxEntry))).scalar_one()
    duplicate = await capture()
    assert duplicate.reason == "duplicate" and "Zurich failover target: cluster blue." in model.prompts[1]
    assert await _revisions(db, workspace_id) == 1
    assert (await db.execute(select(func.count()).select_from(KnowledgeProjectionOutboxEntry))).scalar_one() == (
        outbox_before
    )

    # A sub-agent turn never writes the episode.
    child_id = await _session_with_turn(db, workspace_id=workspace_id, user_id=member_id, parent_id=session_id)
    assert (await capture_turn_episode(db, session_id=child_id, model_factory=model)).reason == "sub_agent_turn"


async def test_turn_capture_never_raises_and_is_hooked_after_the_memory_capture(db, monkeypatch) -> None:
    def factory_raising(error: Exception):
        async def model_factory(db, *, project_id: str):
            raise error

        return model_factory

    class SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    session_id = await _session_with_turn(db, workspace_id=workspace_id, user_id=member_id)
    await set_episode_policy(db, workspace_id, accepted=True, capture_platform_turns=True)
    # The background entry point rolls back whatever it did not record, so the setup is committed.
    await db.commit()
    monkeypatch.setattr(get_settings(), "platform_public_origin", ORIGIN)

    unconfigured = factory_raising(CaptureModelUnavailableError("needs_configuration", "no_runtime_configured"))
    outcome = await run_turn_episode_capture(
        session_factory=SessionFactory(), session_id=session_id, model_factory=unconfigured
    )
    assert outcome.reason == "model_needs_configuration"
    broken = factory_raising(RuntimeError("provider said something secret"))
    assert (
        await run_turn_episode_capture(session_factory=SessionFactory(), session_id=session_id, model_factory=broken)
    ).reason == "failed"

    # The same post-turn hook as the Memory capture, after it.
    calls: list[str] = []

    async def memory(**kwargs):
        calls.append("memory")

    async def episode(**kwargs):
        calls.append("episode")

    monkeypatch.setattr(turn_follow_up, "run_turn_memory_capture", memory)
    monkeypatch.setattr(turn_follow_up, "run_turn_episode_capture", episode)
    await turn_follow_up.run_completion_follow_up(
        session_factory=SessionFactory(),
        session_id="00000000-0000-0000-0000-000000000000",
        request_id=None,
        completion_follow_up={
            "project_id": None,
            "session_id": "00000000-0000-0000-0000-000000000000",
            "agent_type": "chat",
            "completion_reason": "completed",
            "latest_assistant_message_id": None,
            "latest_assistant_content": "",
        },
    )
    assert calls == ["memory", "episode"]

    # The model call is a registered dispatch owner, admitted in the episode module.
    owner = DISPATCH_OWNERS["knowledge_episode_summary"]
    assert turn_capture.governed_summary_model.__module__.endswith("episodes.summary_model")
    assert owner.requires_admission and owner.admission_module.endswith("episodes/summary_model.py")


async def test_settings_switch_the_sub_setting_alone_and_audit_booleans_only(client, db, auth_headers) -> None:
    workspace_id = await seed_workspace(db)
    await db.commit()
    url = f"/api/v1/workspaces/{workspace_id}/knowledge/episodes/settings"

    initial = await client.get(url, headers=auth_headers)
    assert (initial.json()["accept_session_episodes"], initial.json()["capture_platform_turns"]) == (False, False)
    assert (await client.put(url, json={}, headers=auth_headers)).status_code == 422

    changed = await client.put(url, json={"capture_platform_turns": True}, headers=auth_headers)
    assert changed.status_code == 200, changed.text
    assert (changed.json()["accept_session_episodes"], changed.json()["capture_platform_turns"]) == (False, True)
    # Resending the same value changes nothing and is not audited again.
    await client.put(url, json={"capture_platform_turns": True, "accept_session_episodes": False}, headers=auth_headers)

    audits = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.action == POLICY_AUDIT_ACTION, AuditLog.resource_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )
    assert [audit.details for audit in audits] == [
        {"workspace_id": workspace_id, "changes": {"capture_platform_turns": {"old": False, "new": True}}}
    ]
    assert audits[0].resource_type == "workspace"


async def test_the_chat_tool_saves_the_runs_own_session_through_the_governed_writer(
    db, evidence_runtime, public_origin
) -> None:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    other_id = await seed_member(db, workspace_id=workspace_id, role="member")
    own = Session(user_id=member_id, project_id=workspace_id, agent_type="chat")
    foreign = Session(user_id=other_id, project_id=workspace_id, agent_type="chat")
    db.add_all([own, foreign])
    await db.flush()
    tool = KnowledgeEpisodeSummaryTool()
    params = {"summary": f"Pinned the Zurich failover to cluster blue. Token {SECRET}.", "title": "Failover"}

    def context(session_id: str, *, depth: int = 0):
        ctx = tool_context(user_id=member_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
        ctx.session_id = session_id
        ctx.sub_agent_depth = depth
        return ctx

    refused = await tool.execute(params, context(own.id))
    assert (refused["state"], refused["reason"]) == ("needs_configuration", "episodes_disabled")
    await set_episode_policy(db, workspace_id, accepted=True)
    assert (await tool.execute(params, context(own.id, depth=1)))["state"] == "denied"
    assert (await tool.execute(params, context(foreign.id)))["reason"] == "invalid_session"

    recorded = await tool.execute({**params, "project_id": "ignored", "session_id": foreign.id}, context(own.id))
    assert (recorded["state"], recorded["kind"], recorded["redactions"]) == ("recorded", "session_episode", 1)
    assert recorded["source_key"] == f"session-episode.{own.id}"
    assert recorded["source_url"] == f"{ORIGIN}/chat?session_id={own.id}"
    again = await tool.execute(params, context(own.id))
    assert (again["state"], again["revision_id"]) == ("duplicate", recorded["revision_id"])

    # Governance: a built-in internal write that needs the change capability.
    assert "knowledge_episode_summary" in TOOL_REGISTRY
    assert "knowledge_episode_summary" in BUILT_IN_INTERNAL_WRITE_DEFINITION_NAMES
    metadata = get_tool_definition_metadata("knowledge_episode_summary")
    assert (metadata.risk, metadata.owner_type, metadata.mutates_state) == ("write", "built_in", True)
    assert tool_required_capability("knowledge_episode_summary") == "change"
