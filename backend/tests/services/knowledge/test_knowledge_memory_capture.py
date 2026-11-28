"""Automatic memory capture at turn end is off by default, never runs for a sub-agent, writes only what the user stated as inferred and unconfirmed, and in the background never raises and stays bounded."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import select

from app.models import Message, Session
from app.models.project.knowledge_memory import KnowledgeMemoryItem
from app.services.knowledge.memory.auto_capture import capture_turn_memories, run_turn_memory_capture
from app.services.knowledge.memory.capture_model import CaptureModelUnavailableError
from app.services.knowledge.memory.settings import set_automatic_capture
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace


class FakeCaptureModel:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, db, *, project_id: str):
        return self

    async def json(self, *, system: str, user: str) -> dict:
        self.prompts.append(user)
        return self.answer


async def _turn(db, *, workspace_id: str, user_id: str, user_text: str, answer: str, parent_id: str | None = None):
    session = Session(user_id=user_id, project_id=workspace_id, agent_type="diagnosis", parent_session_id=parent_id)
    db.add(session)
    await db.flush()
    started = utc_now()
    db.add(Message(session_id=session.id, role="user", content=user_text, created_at=started))
    db.add(Message(session_id=session.id, role="assistant", content=answer, created_at=started + timedelta(seconds=1)))
    await db.flush()
    return session.id


async def _memories(db, workspace_id: str) -> list[KnowledgeMemoryItem]:
    rows = await db.execute(select(KnowledgeMemoryItem).where(KnowledgeMemoryItem.project_id == workspace_id))
    return list(rows.scalars())


USER_TEXT = (
    "From now on I prefer answers with code examples in Kotlin. Also we decided the team deploys only on "
    "Tuesdays. My staging password=Hunter2Hunter2 is in the vault."
)


ANSWER = "Understood. The Kotlin examples will follow; always use feature flags for risky changes."


CANDIDATES = {
    "memories": [
        {
            "class": "personal",
            "text": "Prefers code examples in Kotlin.",
            "user_quote": "I prefer answers with code examples in Kotlin",
        },
        # Only the assistant said this: not a statement of the user.
        {
            "class": "learning",
            "text": "Always use feature flags.",
            "user_quote": "always use feature flags for risky changes",
        },
        # A secret the user typed is refused, not stored.
        {
            "class": "personal",
            "text": "Staging password=Hunter2Hunter2.",
            "user_quote": "My staging password=Hunter2Hunter2",
        },
    ]
}


async def test_automatic_capture_is_off_by_default_and_never_runs_for_a_sub_agent(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    model = FakeCaptureModel(CANDIDATES)
    session_id = await _turn(db, workspace_id=workspace_id, user_id=user_id, user_text=USER_TEXT, answer=ANSWER)

    assert (await capture_turn_memories(db, session_id=session_id, model_factory=model)).reason == "disabled"
    await set_automatic_capture(db, workspace_id, enabled=True)
    child_id = await _turn(
        db, workspace_id=workspace_id, user_id=user_id, user_text=USER_TEXT, answer=ANSWER, parent_id=session_id
    )
    assert (await capture_turn_memories(db, session_id=child_id, model_factory=model)).reason == "sub_agent_turn"
    assert model.prompts == [] and await _memories(db, workspace_id) == []


async def test_enabled_capture_writes_only_what_the_user_stated_as_inferred_and_unconfirmed(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await set_automatic_capture(db, workspace_id, enabled=True)
    session_id = await _turn(db, workspace_id=workspace_id, user_id=user_id, user_text=USER_TEXT, answer=ANSWER)
    team = {
        "class": "decision",
        "text": "The team deploys on Tuesdays.",
        "user_quote": "we decided the team deploys only on Tuesdays",
    }
    model = FakeCaptureModel({"memories": [*CANDIDATES["memories"][:2], team]})

    outcome = await capture_turn_memories(db, session_id=session_id, model_factory=model)
    # The personal preference is written; the assistant's words are rejected; a member cannot write team memory.
    assert (outcome.reason, outcome.recorded, outcome.skipped) == ("captured", 1, 2)
    [item] = await _memories(db, workspace_id)
    assert (item.author_class, item.state, item.scope, item.owner_user_id) == (
        "model_inferred",
        "observed",
        "user",
        user_id,
    )
    assert item.text == "Prefers code examples in Kotlin." and item.session_id == session_id
    turn = (
        await db.execute(select(Message.id).where(Message.session_id == session_id, Message.role == "user"))
    ).scalar_one()
    assert item.turn_ref == turn
    # Only user-visible messages reach the model.
    assert model.prompts[0].startswith("User message:\n" + USER_TEXT)

    # Secrets are refused; restating a memory (even a corrected, superseded one) never duplicates it.
    item.state = "superseded"
    await db.flush()
    again = await capture_turn_memories(db, session_id=session_id, model_factory=FakeCaptureModel(CANDIDATES))
    assert (again.reason, again.recorded, again.skipped) == ("nothing_to_capture", 0, 3)
    assert len(await _memories(db, workspace_id)) == 1


async def test_the_background_capture_never_raises_and_is_bounded(db, monkeypatch):
    import app.services.knowledge.memory.auto_capture as module

    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await set_automatic_capture(db, workspace_id, enabled=True)
    session_id = await _turn(db, workspace_id=workspace_id, user_id=user_id, user_text=USER_TEXT, answer=ANSWER)
    await db.commit()

    @asynccontextmanager
    async def same_session():
        yield db

    async def unavailable(db, *, project_id):
        raise CaptureModelUnavailableError("needs_configuration", "no_runtime_configured")

    async def broken(db, *, project_id):
        raise RuntimeError("provider text that must never be logged")

    class SlowModel:
        async def json(self, *, system, user):
            await asyncio.sleep(1)

    async def slow(db, *, project_id):
        return SlowModel()

    run = run_turn_memory_capture
    assert (await run(session_factory=same_session, session_id=session_id, model_factory=unavailable)).reason == (
        "model_needs_configuration"
    )
    assert (await run(session_factory=same_session, session_id=session_id, model_factory=broken)).reason == "failed"
    monkeypatch.setattr(module, "AUTO_CAPTURE_TIMEOUT_SECONDS", 0.05)
    assert (await run(session_factory=same_session, session_id=session_id, model_factory=slow)).reason == "timeout"
