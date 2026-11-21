"""Runtime-error salvage answers from loaded knowledge evidence and from created presentations."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.standard_loop import _build_runtime_error_salvage_message
from app.models.project import Project
from app.models.runtime.audit import ToolCall
from app.models.security.user import User
from app.models.session import Session
from tests.standard_loop_salvage_support import TURN_STARTED_AT


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_answers_from_loaded_knowledge_evidence(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"knowledge-salvage-{uuid.uuid4().hex[:6]}", is_active=True)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="diagnosis",
        status="active",
    )
    db.add_all(
        [
            project,
            session,
            ToolCall(
                session_id=session.id,
                tool_name="knowledge_search",
                parameters={"query": "Report Builder"},
                result={
                    "state": "ok",
                    "result_count": 1,
                    "evidence": [
                        {
                            "source_title": "report-builder-guide",
                            "text": (
                                "Report Builder is the Acme Orders reporting component and builds "
                                "weekly order reports from the shop's exports."
                            ),
                            "cite_as": "confluence://report-builder",
                        }
                    ],
                },
                status="success",
            ),
        ]
    )
    await db.commit()

    message = await _build_runtime_error_salvage_message(
        db=db,
        session_id=session.id,
        turn_started_at=TURN_STARTED_AT,
        request_messages=[{"role": "user", "content": "what can you tell me about Report Builder?"}],
    )

    assert "Report Builder is the Acme Orders reporting component" in message
    assert "report-builder-guide" in message
    assert "confluence://report-builder" in message
    assert "Agent reached maximum" not in message


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_mentions_created_presentation(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
    )
    db.add(session)
    await db.flush()
    db.add(
        ToolCall(
            session_id=session.id,
            tool_name="create_office_document",
            parameters={"doc_type": "pptx", "file_path": "report_builder_presentation.pptx"},
            result={
                "success": True,
                "relative_path": "report_builder_presentation.pptx",
                "file_path": "/tmp/report_builder_presentation.pptx",
            },
            status="success",
        )
    )
    await db.commit()

    message = await _build_runtime_error_salvage_message(
        db=db,
        session_id=session.id,
        turn_started_at=TURN_STARTED_AT,
        request_messages=[
            {
                "role": "user",
                "content": (
                    "Erstelle mir aus dem Wissen zu report-builder eine Presentation mit klarer Struktur, "
                    "Kernfunktionen, Integration und wichtigsten Betriebsaspekten."
                ),
            }
        ],
    )

    assert "presentation" in message.lower()
    assert "report_builder_presentation.pptx" in message
    assert "core capabilities" in message.lower()
    assert "Integration" in message
    assert "operational considerations" in message.lower()


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_builds_presentation_outline_from_evidence(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="change",
        status="active",
    )
    db.add(session)
    await db.flush()
    db.add(
        ToolCall(
            session_id=session.id,
            tool_name="get_confluence_page",
            parameters={"page_id": "12345"},
            result={"title": "Report Builder Architektur"},
            status="success",
        )
    )
    await db.commit()

    message = await _build_runtime_error_salvage_message(
        db=db,
        session_id=session.id,
        turn_started_at=TURN_STARTED_AT,
        request_messages=[
            {
                "role": "user",
                "content": (
                    "Erstelle mir aus dem Wissen zu report-builder eine Presentation mit klarer Struktur, "
                    "Kernfunktionen, Integration und wichtigsten Betriebsaspekten."
                ),
            }
        ],
    )

    assert "Slide 1" in message
    assert "core capabilities" in message.lower()
    assert "Integration" in message
