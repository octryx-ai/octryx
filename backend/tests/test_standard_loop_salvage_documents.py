"""Runtime-error salvage for created document scripts and document artifacts behind evidence noise."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agent.core.runtime.standard_loop import _build_runtime_error_salvage_message
from app.models.project import Project
from app.models.runtime.audit import ToolCall
from app.models.security.user import User
from app.models.session import Session
from tests.standard_loop_salvage_support import TURN_STARTED_AT


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_mentions_created_document_script_artifact(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="documentation",
        status="active",
    )
    db.add(session)
    await db.flush()
    db.add_all(
        [
            ToolCall(
                session_id=session.id,
                tool_name="build_word_template_script",
                parameters={"file_path": "ticketing_research_document.docx"},
                result={
                    "success": True,
                    "relative_path": "ticketing_research_document.docx",
                    "file_path": "/tmp/ticketing_research_document.docx",
                    "validation": {"valid": True},
                },
                status="success",
            ),
            ToolCall(
                session_id=session.id,
                tool_name="get_office_document_info",
                parameters={"file_path": "ticketing_research_document.docx"},
                result={"relative_path": "ticketing_research_document.docx", "paragraph_count": 12},
                status="success",
            ),
        ]
    )
    await db.commit()

    message = await _build_runtime_error_salvage_message(
        db=db,
        session_id=session.id,
        turn_started_at=TURN_STARTED_AT,
        request_messages=[
            {
                "role": "user",
                "content": "Research ticketing API integration and create a cited Word document.",
            }
        ],
    )

    assert "ticketing_research_document.docx" in message
    assert "generated the requested office artifact" in message.lower()


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_finds_document_artifact_after_evidence_noise(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project.id,
        agent_type="documentation",
        status="active",
    )
    db.add(session)
    await db.flush()

    base_time = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)
    db.add_all(
        [
            ToolCall(
                session_id=session.id,
                tool_name="build_word_template_script",
                parameters={"file_path": "ticketing_research_document.docx"},
                result={
                    "_artifact_storage": "external_json_gzip",
                    "artifact_id": "tool-artifact-1",
                    "preview": {
                        "compact_result": {
                            "success": True,
                            "relative_path": "ticketing_research_document.docx",
                            "file_path": "/tmp/ticketing_research_document.docx",
                            "validation": {"valid": True},
                        }
                    },
                },
                status="success",
                created_at=base_time,
            ),
            ToolCall(
                session_id=session.id,
                tool_name="get_office_document_info",
                parameters={"file_path": "ticketing_research_document.docx"},
                result={"relative_path": "ticketing_research_document.docx", "paragraph_count": 24},
                status="success",
                created_at=base_time + timedelta(seconds=1),
            ),
            *[
                ToolCall(
                    session_id=session.id,
                    tool_name="ingest_document_source",
                    parameters={"url": f"https://developer.example.com/source-{index}"},
                    result={"source": {"url": f"https://developer.example.com/source-{index}"}},
                    status="success",
                    created_at=base_time + timedelta(seconds=2 + index),
                )
                for index in range(20)
            ],
        ]
    )
    await db.commit()

    message = await _build_runtime_error_salvage_message(
        db=db,
        session_id=session.id,
        turn_started_at=TURN_STARTED_AT,
        request_messages=[
            {
                "role": "user",
                "content": "Research ticketing API integration and create a cited Word document.",
            }
        ],
    )

    assert "ticketing_research_document.docx" in message
    assert "generated the requested office artifact" in message.lower()
