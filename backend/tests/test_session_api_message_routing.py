import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Message, Project, Session, User
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.message_dispatch import send_session_message
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY


async def _dispatch(db, **kwargs: Any) -> None:
    """The /api/v1 dispatch with its completion follow-up on the test database, awaited."""
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    await send_session_message(db, session_factory=session_factory, **kwargs)
    await drain_chat_turn_background_tasks(kwargs["session_id"])


@pytest.mark.asyncio
async def test_send_session_message_stores_workflow_routing_policy_resolution(db, monkeypatch) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    async def fake_resolver(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "source": "db",
            "status": "matched",
            "workflow_id": "source_evidence_lookup",
            "workflow_class": "source_evidence_lookup",
            "workflow_contract": {
                "workflow_id": "source_evidence_lookup",
                "source_steps": [{"tool": "list_jira_versions", "args": {}}],
            },
            "tool_policy": {"allowlist": ["list_jira_versions"], "denylist": []},
            "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
        }

    async def fake_run_agent_func(*args: Any, **kwargs: Any):
        if False:
            yield {}

    monkeypatch.setattr("app.services.session.turn_routing_resolution.resolve_workflow_selection_for_turn", fake_resolver)

    await _dispatch(
        db,
        session_id=session.id,
        content="What is the latest release?",
        user_id=admin.id,
        project_id=project.id,
        agent_type="diagnosis",
        run_agent_func=fake_run_agent_func,
    )

    await db.refresh(session)
    assert session.metadata_[ROUTING_RESOLUTION_KEY]["workflow_id"] == "source_evidence_lookup"
    # Prepared like /chat/api: the execution strategy decides the expected workflow, and the
    # execution profile is always built.
    assert session.metadata_["execution_profile"]["profile_id"]
    # cross-device mirror: the (empty = standard) selection is recorded
    assert session.metadata_["workflow_key"] == ""
    message_count = (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert len(message_count) == 1


@pytest.mark.asyncio
async def test_send_session_message_honors_explicit_workflow_key(db) -> None:
    """/api/v1 dispatch resolves workflow_key deterministically (no keyword match needed)."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    async def fake_run_agent_func(*args: Any, **kwargs: Any):
        if False:
            yield {}

    await _dispatch(
        db,
        session_id=session.id,
        content="Bitte erstelle die Uebersicht.",  # no routing keywords
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        run_agent_func=fake_run_agent_func,
        workflow_key="incident-analysis",
    )

    await db.refresh(session)
    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    # A phased key holds its start card (a workflow run), never a keyword-matched workflow.
    assert (resolution["source"], resolution["status"]) == ("workflow_proposal", "needs_confirmation")
    proposal = resolution["workflow_proposal"]
    assert (proposal["reason_code"], proposal["workflow_key"]) == ("explicit_phased_selection", "incident-analysis")
    assert proposal["dispatch"] is None
    assert session.metadata_["workflow_key"] == "incident-analysis"


@pytest.mark.asyncio
async def test_send_session_message_unknown_workflow_key_has_no_keyword_fallback(db) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    async def fake_run_agent_func(*args: Any, **kwargs: Any):
        if False:
            yield {}

    await _dispatch(
        db,
        session_id=session.id,
        content="Create an AWS topology architecture diagram.",  # would keyword-match
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        run_agent_func=fake_run_agent_func,
        workflow_key="does-not-exist",
    )

    await db.refresh(session)
    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    assert resolution["status"] == "unknown_key"
    assert resolution["workflow_id"] is None
    # Prepared like /chat/api: the unknown key is an explicit clarification state, never a
    # keyword-matched workflow of the routing resolution.
    assert session.metadata_["execution_profile"]["status"] == "needs_clarification"
