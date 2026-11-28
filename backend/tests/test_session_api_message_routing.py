"""``/api/v1`` messages naming a workflow are prepared and held by the execution gate (the start card), never routed
by keywords."""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Session, User
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.message_dispatch import send_session_message
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY


async def _dispatch(db, **kwargs: Any) -> None:
    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    await send_session_message(db, session_factory=session_factory, **kwargs)
    await drain_chat_turn_background_tasks(kwargs["session_id"])


@pytest.mark.asyncio
async def test_send_session_message_honors_explicit_workflow_key(db) -> None:
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

    await _dispatch(
        db,
        session_id=session.id,
        content="Bitte erstelle die Uebersicht.",  # no routing keywords
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
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

    await _dispatch(
        db,
        session_id=session.id,
        content="Create an AWS topology architecture diagram.",  # would keyword-match
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        workflow_key="does-not-exist",
    )

    await db.refresh(session)
    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    assert resolution["status"] == "unknown_key"
    assert resolution["workflow_id"] is None
    # Prepared like /chat/api: the unknown key is an explicit clarification state, never a
    # keyword-matched workflow of the routing resolution.
    assert session.metadata_["execution_profile"]["status"] == "needs_clarification"
