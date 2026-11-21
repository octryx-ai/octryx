import pytest
from sqlalchemy import select

from app.agent.core.turn.turn_state import persist_runtime_assistant_response
from app.models import Session, TurnTrace, User


@pytest.mark.asyncio
async def test_persist_runtime_assistant_response_stores_thinking_in_turn_trace(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(user_id=admin.id, agent_type="chat")
    db.add(session)
    await db.commit()

    response = {
        "content": "Final answer",
        "thinking": "Internal reasoning trace",
        "tool_calls": [],
        "model": "gemma4:e4b",
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }

    assistant_message, turn_trace = await persist_runtime_assistant_response(
        db=db,
        session_id=session.id,
        provider="ollama",
        model="gemma4:e4b",
        request_messages=[{"role": "user", "content": "Hallo"}],
        context_snapshot={"thinking_level": "deep"},
        response=response,
        runtime_attempts=[{"provider": "ollama", "model": "gemma4:e4b", "status": "success"}],
        content="Final answer",
        tool_calls=[],
    )

    assert assistant_message.content == "Final answer"
    assert turn_trace.raw_output["thinking"] == "Internal reasoning trace"

    stored_trace = (await db.execute(select(TurnTrace).where(TurnTrace.id == turn_trace.id))).scalar_one()
    assert stored_trace.message_id == assistant_message.id
    assert stored_trace.raw_output["thinking"] == "Internal reasoning trace"
