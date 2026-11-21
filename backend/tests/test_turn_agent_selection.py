"""The explicit agent selection of a turn: closed sources, precedence, no prompt scoring."""

import pytest
from fastapi import HTTPException

from app.services.session.agent_selection_sources import AgentSelectionSource, session_bound_agent_id
from tests.turn_agent_selection_support import _workspace
from tests.turn_preparation_support import prepare_chat_turn


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected",
    [
        AgentSelectionSource.EXPLICIT,
        AgentSelectionSource.SESSION,
        AgentSelectionSource.MENTION,
        AgentSelectionSource.DEFAULT,
    ],
)
async def test_each_source_wins_in_precedence_order(db, expected):
    ws = await _workspace(db, default_agent=True)
    order = list(AgentSelectionSource)
    # Offer every source ranked at or below the expected one; the expected one must win.
    offered = set(order[order.index(expected) :])
    mention = ws.agents["mention"].name
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db,
        user=ws.admin,
        prompt=f"@{mention} summarize the open work" if AgentSelectionSource.MENTION in offered else "Summarize it.",
        project_id=ws.project.id,
        session_id=ws.session.id if AgentSelectionSource.SESSION in offered else "",
        agent_id=ws.agents["explicit"].id if AgentSelectionSource.EXPLICIT in offered else "",
    )

    assert payload is not None
    assert payload["id"] == ws.agents[expected.value].id
    assert session.metadata_["agent_definition_id"] == ws.agents[expected.value].id
    assert session.metadata_["agent_selection_source"] == expected.value
    assert "auto_selected_agent_reason" not in session.metadata_


@pytest.mark.asyncio
async def test_without_any_source_the_turn_runs_as_the_platform_assistant(db):
    # There is no anonymous turn: the platform Assistant answers, explicitly recorded.
    ws = await _workspace(db, default_agent=False)
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db, user=ws.admin, prompt="Summarize the open work.", project_id=ws.project.id
    )

    assert payload["builtinKey"] == "assistant"
    assert session.metadata_["agent_definition_id"] == payload["id"]
    assert session.metadata_["agent_selection_source"] == "platform_default"
    assert session.metadata_["agent_key"] == "assistant"


@pytest.mark.asyncio
async def test_an_explicit_agent_type_skips_session_and_workspace_default(db):
    ws = await _workspace(db, default_agent=True)
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db,
        user=ws.admin,
        prompt="Summarize the open work.",
        project_id=ws.project.id,
        session_id=ws.session.id,
        agent_type="diagnosis",
        agent_type_explicit=True,
    )

    assert payload["builtinKey"] == "assistant"
    assert session.metadata_["agent_selection_source"] == "platform_default"
    assert session.agent_type == "diagnosis"


@pytest.mark.asyncio
async def test_the_session_agent_is_reused_without_keyword_checks(db):
    # A plain follow-up keeps the selected delivery agent, even when it reads as
    # "diagnosis" (the default intent of every turn without a workflow).
    ws = await _workspace(db, default_agent=False)
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db,
        user=ws.admin,
        prompt="Check the AWS account identity and do not change anything.",
        project_id=ws.project.id,
        session_id=ws.session.id,
    )

    assert payload is not None
    assert payload["id"] == ws.agents["session"].id
    assert session.metadata_["agent_selection_source"] == "session"


@pytest.mark.asyncio
async def test_a_mention_overrides_the_bound_agent_for_its_turn_only(db):
    # An explicit @mention outranks the session's bound agent, for that turn.
    ws = await _workspace(db, default_agent=False)
    mentioned = ws.agents["mention"]
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db,
        user=ws.admin,
        prompt=f"@{mentioned.name} review the last change",
        project_id=ws.project.id,
        session_id=ws.session.id,
    )
    assert payload["id"] == mentioned.id
    assert session.metadata_["agent_selection_source"] == "mention"
    # The next plain turn reuses the binding, not the mentioned agent.
    assert session_bound_agent_id(session.metadata_) == ws.agents["session"].id


@pytest.mark.asyncio
async def test_a_mention_in_a_session_without_a_bound_agent_binds_it(db):
    ws = await _workspace(db, default_agent=False)
    mentioned = ws.agents["mention"]
    session, _runtime, _thinking, _payload = await prepare_chat_turn(
        db=db, user=ws.admin, prompt=f"@{mentioned.name} start the review", project_id=ws.project.id
    )
    assert session_bound_agent_id(session.metadata_) == mentioned.id


@pytest.mark.asyncio
async def test_a_plain_turn_reuses_the_bound_agent_not_the_last_mentioned_one(db):
    ws = await _workspace(db, default_agent=False)
    ws.session.metadata_ = {
        "agent_definition_id": ws.agents["mention"].id,
        "bound_agent_definition_id": ws.agents["session"].id,
    }
    await db.commit()
    session, _runtime, _thinking, payload = await prepare_chat_turn(
        db=db, user=ws.admin, prompt="Continue.", project_id=ws.project.id, session_id=ws.session.id
    )
    assert payload["id"] == ws.agents["session"].id
    assert session.metadata_["agent_selection_source"] == "session"
    assert session.metadata_["bound_agent_definition_id"] == ws.agents["session"].id


@pytest.mark.asyncio
async def test_an_ambiguous_mention_refuses_the_turn(db):
    ws = await _workspace(db, default_agent=False)
    with pytest.raises(HTTPException) as refused:
        await prepare_chat_turn(
            db=db,
            user=ws.admin,
            prompt=f"@{ws.agents['mention'].name} and @{ws.agents['explicit'].name} compare notes",
            project_id=ws.project.id,
        )
    assert refused.value.status_code == 409
