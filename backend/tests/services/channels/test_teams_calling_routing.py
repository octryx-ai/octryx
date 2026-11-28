import uuid

import pytest

from app.models import CallAgentConfig, Project
from app.services.call_agent import CallAgentResponse
from app.services.teams_calling.agent_orchestration import agent_response
from app.services.teams_calling.call_session_state import cleanup_call_state, get_call_state


@pytest.mark.asyncio
async def test_agent_response_uses_persisted_project_call_agent_config(db, monkeypatch):
    project = Project(id=str(uuid.uuid4()), name=f"Calling Project {uuid.uuid4()}")
    db.add(project)
    config = CallAgentConfig(
        id=str(uuid.uuid4()),
        name="Project CallAgent",
        project_id=project.id,
        channel_id=None,
        system_prompt="Answer meeting questions.",
        enabled_tools=["knowledge_search"],
        is_active=True,
    )
    db.add(config)
    await db.commit()
    calls = {}

    class FakeCallAgentService:
        def __init__(self, db_arg, config_arg):
            calls["config"] = config_arg

        async def run(self, user_message, transcript_context=""):
            calls["user_message"] = user_message
            calls["transcript_context"] = transcript_context
            return CallAgentResponse(final_response="Persisted config response")

    monkeypatch.setattr("app.services.call_agent.CallAgentService", FakeCallAgentService)
    call_state = get_call_state("call-routing-1")
    call_state.add_user_segment("Earlier meeting context", duration_ms=1000)

    response = await agent_response(
        text="Hey Octryx, summarize status",
        call_id="call-routing-1",
        channel_id="2",
        db=db,
        project_id=project.id,
    )

    assert response == "Persisted config response"
    assert calls["config"].id == config.id
    assert calls["user_message"] == "Hey Octryx, summarize status"
    assert "Earlier meeting context" in calls["transcript_context"]
    cleanup_call_state("call-routing-1")


@pytest.mark.asyncio
async def test_agent_response_reports_missing_call_agent_config(db):
    project = Project(id=str(uuid.uuid4()), name=f"Calling Project {uuid.uuid4()}")
    db.add(project)
    await db.commit()

    response = await agent_response(
        text="Hey Octryx, summarize status",
        call_id="call-routing-missing",
        channel_id="2",
        db=db,
        project_id=project.id,
    )

    assert response == "Sorry, no active call agent is configured for this project."
