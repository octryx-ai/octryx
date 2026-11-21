"""Tests for ask_clarification tool."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models import ClarificationQuestion
from app.tools.clarification import AskClarificationTool
from app.tools.definitions.clarification import get_clarification_definitions


def test_ask_clarification_tool_registered():
    """Tool definition is present in the registry."""
    definitions = get_clarification_definitions()
    assert "ask_clarification" in definitions
    func = definitions["ask_clarification"]["function"]
    assert func["name"] == "ask_clarification"
    params = func["parameters"]["properties"]
    assert "question" in params
    assert "question_id" in params
    assert "priority" in params
    assert "context_snapshot" in params


@pytest.mark.asyncio
async def test_ask_clarification_tool_requires_question_and_question_id():
    tool = AskClarificationTool()
    context = MagicMock()
    context.session_id = "test-session"
    context.user_id = "test-user"
    context.project_config = {}
    context.db = None

    result = await tool.execute({}, context)
    assert "error" in result


@pytest.mark.asyncio
async def test_ask_clarification_tool_requires_session_id():
    tool = AskClarificationTool()
    context = MagicMock()
    context.session_id = None
    context.user_id = "test-user"
    context.project_config = {}
    context.db = None

    result = await tool.execute(
        {"question": "Test?", "question_id": "test-1"},
        context,
    )
    assert "error" in result
    assert "session_id" in result["error"]


@pytest.mark.asyncio
async def test_ask_clarification_tool_uses_existing_context_db_session(db):
    tool = AskClarificationTool()
    context = MagicMock()
    context.session_id = "test-session"
    context.user_id = "test-user"
    context.project_config = {}
    context.db = db

    result = await tool.execute(
        {"question": "Which repository should be changed?", "question_id": "repo-scope"},
        context,
    )

    persisted = (
        await db.execute(
            select(ClarificationQuestion).where(
                ClarificationQuestion.session_id == "test-session",
                ClarificationQuestion.question_id == "repo-scope",
            )
        )
    ).scalar_one()
    assert result["status"] == "paused"
    assert result["question_id"] == persisted.id
    assert persisted.question_text == "Which repository should be changed?"


@pytest.mark.asyncio
async def test_ask_clarification_tool_definitions():
    """Verify the tool schema includes required fields."""
    definitions = get_clarification_definitions()
    params = definitions["ask_clarification"]["function"]["parameters"]
    required = params.get("required", [])
    assert "question" in required
    assert "question_id" in required

    priority_prop = params["properties"]["priority"]
    assert priority_prop["type"] == "string"
    assert "low" in priority_prop["enum"]
    assert "critical" in priority_prop["enum"]


def test_ask_clarification_tool_name():
    tool = AskClarificationTool()
    assert tool.name == "ask_clarification"


def test_ask_clarification_tool_description():
    tool = AskClarificationTool()
    assert "pause" in tool.description.lower() or "clarification" in tool.description.lower()
