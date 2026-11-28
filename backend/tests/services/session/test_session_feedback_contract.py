import uuid

import pytest

from app.api.routes.sessions._session_api_helpers import submit_message_feedback
from app.exceptions.api import ConflictError
from app.exceptions.contract import get_error_contract
from app.models import Message, Project, Session
from app.schemas.admin.admin_panel._chat import MessageFeedbackRequest
from app.services.session.feedback import get_session_message_feedback, submit_session_message_feedback
from tests.devices.device_support import user_named
from tests.policy_engine_support import bearer


@pytest.mark.asyncio
async def test_submit_message_feedback_uses_domain_validation_contract(db):
    with pytest.raises(ConflictError) as exc_info:
        await submit_session_message_feedback(
            db,
            session_id=str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            rating=0,
            user_id=str(uuid.uuid4()),
        )

    contract = get_error_contract(exc_info.value)
    assert contract.error_code == "session_feedback_invalid_request"
    assert contract.retryable is False


@pytest.mark.asyncio
async def test_submit_session_message_feedback_service_roundtrip(db, auth_user):
    project = Project(id=str(uuid.uuid4()), name=f"feedback-{uuid.uuid4().hex[:8]}", config={}, is_active=True)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="A generic answer.",
    )
    db.add_all([project, session, message])
    await db.commit()

    feedback = await submit_message_feedback(
        db,
        session_id=session.id,
        message_id=message.id,
        body=MessageFeedbackRequest(rating="bad", disliked="too generic"),
        user_id=auth_user.id,
    )

    assert feedback.message_id == message.id
    assert (feedback.rating, feedback.liked, feedback.disliked) == ("bad", None, "too generic")
    fetched = await get_session_message_feedback(
        db,
        session_id=session.id,
        message_id=message.id,
        user_id=auth_user.id,
    )
    assert fetched is not None
    assert (fetched.message_id, fetched.rating, fetched.disliked) == (message.id, "bad", "too generic")


@pytest.mark.asyncio
async def test_session_feedback_api_preserves_not_found_payload(client, auth_headers):
    resp = await client.post(
        f"/api/v1/sessions/{uuid.uuid4()}/messages/{uuid.uuid4()}/feedback",
        headers=auth_headers,
        json={"rating": "good", "liked": "missing session"},
    )

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["detail"] == "Session not found"
    assert payload["error"] == "Session not found"


@pytest.mark.asyncio
async def test_session_feedback_api_preserves_validation_payload(client, db):
    member = await user_named(db, f"feedback-member-{uuid.uuid4().hex[:6]}")
    await db.commit()
    resp = await client.post(
        f"/api/v1/sessions/{uuid.uuid4()}/messages/{uuid.uuid4()}/feedback",
        headers=bearer(member.id),
        json={"rating": 0, "comment": "invalid rating"},
    )

    # Closed values only: the retired integer rating and the free comment are refused, not coerced.
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_session_feedback_api_preserves_conflict_payload(client, auth_headers, db, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        agent_type="chat",
        status="active",
        metadata_={},
    )
    db.add(session)
    message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="hello",
    )
    db.add(message)
    await db.commit()

    resp = await client.post(
        f"/api/v1/sessions/{session.id}/messages/{message.id}/feedback",
        headers=auth_headers,
        json={"rating": "bad", "disliked": "not assistant"},
    )

    assert resp.status_code == 400
    payload = resp.json()
    assert payload["detail"] == "Only assistant messages can be rated"
    assert payload["error"] == "Only assistant messages can be rated"
