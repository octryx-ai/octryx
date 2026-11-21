"""Runtime-error salvage building an AWS partial evidence report, or preferring a completed diagram over it."""

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.runtime.standard_loop import _build_runtime_error_salvage_message
from app.models.runtime.audit import ToolCall
from app.models.security.user import User
from app.models.session import Session
from tests.standard_loop_salvage_support import TURN_STARTED_AT


@pytest.mark.asyncio
async def test_runtime_error_salvage_message_builds_aws_partial_evidence_report(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        agent_type="diagnosis",
        status="active",
    )
    db.add(session)
    await db.flush()
    db.add_all(
        [
            ToolCall(
                session_id=session.id,
                tool_name="aws_read_operation",
                parameters={"service": "sts", "operation": "get-caller-identity"},
                result={
                    "service": "sts",
                    "operation": "get-caller-identity",
                    "result": {
                        "Account": "123456789012",
                        "Arn": "arn:aws:sts::123456789012:assumed-role/octryx-irsa-role/test",
                    },
                },
                status="success",
            ),
            ToolCall(
                session_id=session.id,
                tool_name="list_aws_codepipelines",
                parameters={},
                result={
                    "count": 2,
                    "pipelines": [
                        {"name": "eu-central-1_01-base_apply"},
                        {"name": "eu-central-1_06-octryx_apply"},
                    ],
                },
                status="success",
            ),
            ToolCall(
                session_id=session.id,
                tool_name="search_aws_cloudtrail_events",
                parameters={},
                result={"error": "AccessDenied"},
                status="error",
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
                "content": "Analyze AWS CodePipeline and CloudTrail state in eu-central-1.",
            }
        ],
    )

    assert "tool-iteration limit" in message
    assert "123456789012" in message
    assert "eu-central-1_01-base_apply" in message
    assert "search_aws_cloudtrail_events:error" in message
    assert "Agent reached maximum" not in message


@pytest.mark.asyncio
async def test_runtime_error_salvage_prefers_completed_diagram_over_aws_partial_report(db):
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        agent_type="diagnosis",
        status="active",
    )
    db.add(session)
    await db.flush()
    db.add_all(
        [
            ToolCall(
                session_id=session.id,
                tool_name="aws_topology_snapshot",
                parameters={"services": ["ec2", "eks"], "diagram_detail": "full"},
                result={"account_id": "123456789012", "region": "eu-central-1"},
                status="success",
            ),
            ToolCall(
                session_id=session.id,
                tool_name="create_diagram",
                parameters={"title": "Octryx AWS Topology"},
                result={
                    "preview": {
                        "compact_result": {
                            "status": "created",
                            "diagram_id": "8dc667e0",
                            "title": "Octryx AWS Topology",
                        }
                    }
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
        request_messages=[
            {
                "role": "user",
                "content": "Create a full draw.io AWS topology overview from live topology evidence.",
            }
        ],
    )

    assert "Diagram complete." in message
    assert "diagram://8dc667e0" in message
    assert "Octryx AWS Topology" in message
    assert "partial evidence report" not in message
    assert "tool-iteration limit" not in message
