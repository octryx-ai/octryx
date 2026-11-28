"""Answer feedback in the Memory lobe: closed values and bounds are refused, one feedback per (user, answer),
and the learning surface counts in one Workspace only for admins or owners."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import func, select

from app.api.routes.knowledge.knowledge_feedback import list_workspace_feedback, summarize_workspace_feedback
from app.exceptions.contract import get_error_contract
from app.models import Message, MessageFeedback, Session, TurnTrace
from app.models.project.knowledge_answer_feedback import KnowledgeAnswerFeedback, KnowledgeAnswerFeedbackAspect
from app.models.project.knowledge_memory import KnowledgeMemoryItem
from app.schemas.admin.admin_panel._chat import MessageFeedbackRequest
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.memory.control import forget_memory, list_memory
from app.services.knowledge.memory.errors import MemoryRefusedError
from app.services.knowledge.memory.feedback_contract import parse_answer_feedback
from app.services.session.feedback import SessionFeedbackRefusedError, submit_session_message_feedback
from app.services.session.turn_execution_snapshot import TURN_EXECUTION_SNAPSHOT_KEY, TURN_EXECUTION_SNAPSHOT_VERSION
from app.tools.knowledge_memory.recall import MemoryRecallTool
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace, tool_context

RECALL = MemoryRecallTool()


def _refusal(**payload) -> str:
    with pytest.raises(MemoryRefusedError) as refused:
        parse_answer_feedback(**payload)
    return refused.value.reason


async def _answer(
    db, *, user_id: str, workspace_id: str | None, workflow_key: str | None = "knowledge-request"
) -> Message:
    session = Session(id=str(uuid.uuid4()), user_id=user_id, project_id=workspace_id, agent_type="chat", metadata_={})
    message = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="An answer.", model="m-1")
    db.add_all([session, message])
    await db.flush()
    snapshot = {
        "version": TURN_EXECUTION_SNAPSHOT_VERSION,
        "execution_profile": {
            "present": True,
            "status": "allowed",
            "profile_id": "profile.knowledge",
            "workflow_id": f"wf-{workflow_key}" if workflow_key else None,
            "workflow_key": workflow_key,
        },
        "gate": {"allowed": True, "status": "allowed", "decision_source": "profile"},
    }
    db.add(
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=session.id,
            message_id=message.id,
            provider="bedrock",
            model="eu.amazon.nova-2-lite-v1:0",
            context_snapshot_json={TURN_EXECUTION_SNAPSHOT_KEY: snapshot},
        )
    )
    await db.commit()
    return message


async def _rate(db, message: Message, user_id: str, rating: str, **fields):
    return await submit_session_message_feedback(
        db, session_id=message.session_id, message_id=message.id, rating=rating, user_id=user_id, **fields
    )


def test_feedback_contract_takes_only_closed_values_and_bounded_texts():
    feedback = parse_answer_feedback(
        rating="bad",
        liked="  The sources were linked.  ",
        disliked="",
        aspects={"speed": "disliked", "sources": "liked"},
    )
    assert (feedback.rating, feedback.liked, feedback.disliked) == ("bad", "The sources were linked.", None)
    # The closed order of the contract, whatever order the client sent.
    assert feedback.aspects == (("sources", "liked"), ("speed", "disliked"))

    for rating in (1, -1, "Good", "neutral", None, True):
        assert _refusal(rating=rating) == "invalid_request"
    assert _refusal(rating="good", aspects={"tone": "liked"}) == "invalid_request"
    assert _refusal(rating="good", aspects={"sources": "meh"}) == "invalid_request"
    assert _refusal(rating="good", aspects=["sources"]) == "invalid_request"
    assert _refusal(rating="good", liked="x" * 801) == "invalid_text"
    assert _refusal(rating="good", disliked="bad​spacing") == "invalid_text"
    assert _refusal(rating="bad", disliked="It printed password=Hunter2Hunter2 in the answer") == "secret_detected"
    # Ordinary words that merely contain a token prefix are not secrets.
    assert parse_answer_feedback(rating="good", liked="A risk-based task-list review.").liked is not None

    # The transport schema refuses the retired shape and anything unknown before the service runs.
    for payload in ({"rating": 1}, {"rating": "good", "comment": "x"}, {"rating": "bad", "aspects": {"tone": "liked"}}):
        with pytest.raises(SchemaValidationError):
            MessageFeedbackRequest(**payload)


async def test_one_feedback_per_user_and_answer_lives_in_the_lobe_with_its_links(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    message = await _answer(db, user_id=user_id, workspace_id=workspace_id)

    first = await _rate(
        db,
        message,
        user_id,
        "bad",
        liked="Clear structure.",
        disliked="The Spring Boot 4 migration steps were missing.",
        aspects={"completeness": "disliked", "clarity": "liked"},
    )
    assert (first.rating, first.aspects) == ("bad", {"completeness": "disliked", "clarity": "liked"})

    [row] = (await db.execute(select(KnowledgeAnswerFeedback))).scalars().all()
    assert (row.project_id, row.session_id, row.message_id, row.user_id) == (
        workspace_id,
        message.session_id,
        message.id,
        user_id,
    )
    assert (row.workflow_key, row.workflow_id, row.execution_profile_id) == (
        "knowledge-request",
        "wf-knowledge-request",
        "profile.knowledge",
    )
    assert (row.provider, row.model) == ("bedrock", "eu.amazon.nova-2-lite-v1:0")
    item = await db.get(KnowledgeMemoryItem, row.memory_item_id)
    assert (item.project_id, item.scope, item.owner_user_id, item.item_class) == (
        workspace_id,
        "workspace",
        None,
        "answer_feedback",
    )
    assert (item.author_class, item.state, item.author_user_id) == ("human_stated", "confirmed", user_id)
    assert (item.session_id, item.turn_ref) == (message.session_id, message.id)
    assert "the answer was bad (workflow knowledge-request)" in item.text
    assert "What was not good: The Spring Boot 4 migration steps were missing." in item.text
    # The transport row keeps the integer verdict for analytics and no text.
    transport = (await db.execute(select(MessageFeedback))).scalars().one()
    assert (transport.rating, transport.comment) == (-1, None)

    # Re-submitting replaces the verdict, the texts and every aspect: still one record, one item.
    second = await _rate(db, message, user_id, "good", liked="Now complete.", aspects={"sources": "liked"})
    assert (second.rating, second.liked, second.disliked, second.aspects) == (
        "good",
        "Now complete.",
        None,
        {"sources": "liked"},
    )
    assert (await db.execute(select(func.count()).select_from(KnowledgeAnswerFeedback))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(MessageFeedback))).scalar_one() == 1
    aspects = (await db.execute(select(KnowledgeAnswerFeedbackAspect.aspect))).scalars().all()
    assert aspects == ["sources"]
    items = (await db.execute(select(KnowledgeMemoryItem))).scalars().all()
    assert [entry.id for entry in items] == [item.id]
    assert "migration steps" not in items[0].text and "Now complete." in items[0].text

    # Recalled only when named explicitly; not in the memory list; forgetting erases the texts.
    context = tool_context(user_id=user_id, project_id=workspace_id, project_ids=[workspace_id], db=db)
    assert (await RECALL.execute({"query": "complete"}, context))["state"] == "no_match"
    recalled = await RECALL.execute({"query": "complete", "classes": ["answer_feedback"]}, context)
    assert [entry["memory_id"] for entry in recalled["items"]] == [item.id]
    assert recalled["items"][0]["not_source_evidence"] is True
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, admin_id), workspace_id=workspace_id)
    assert await list_memory(db, authorized=authorized, user_id=admin_id) == []
    await forget_memory(db, authorized=authorized, user_id=admin_id, memory_id=item.id)
    await db.refresh(row)
    assert (row.liked, row.disliked, row.rating) == (None, None, "good")


async def test_feedback_without_a_workspace_or_with_a_secret_is_refused_and_writes_nothing(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    loose = await _answer(db, user_id=user_id, workspace_id=None)
    with pytest.raises(SessionFeedbackRefusedError) as refused:
        await _rate(db, loose, user_id, "good")
    assert (refused.value.state, refused.value.http_status) == ("needs_configuration", 409)
    assert get_error_contract(refused.value).error_code == "session_feedback_workspace_required"

    message = await _answer(db, user_id=user_id, workspace_id=workspace_id)
    with pytest.raises(SessionFeedbackRefusedError) as secret:
        await _rate(db, message, user_id, "bad", disliked="Leaked Authorization: Bearer abcdefghijklmnop123")
    assert (secret.value.reason, secret.value.http_status) == ("secret_detected", 422)
    for model in (KnowledgeAnswerFeedback, KnowledgeMemoryItem, MessageFeedback):
        assert (await db.execute(select(func.count()).select_from(model))).scalar_one() == 0


async def test_learning_surface_filters_counts_and_stays_in_its_workspace(db):
    workspace_id = await seed_workspace(db)
    other_id = await seed_workspace(db)
    admin_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    other_admin_id = await seed_member(db, workspace_id=other_id, role="admin")
    rated = [
        (member_id, "knowledge-request", "bad", {"sources": "disliked", "speed": "liked"}),
        (member_id, "knowledge-request", "good", {"sources": "liked"}),
        (admin_id, "coding-change", "bad", {"correctness": "disliked"}),
    ]
    for user_id, workflow_key, rating, aspects in rated:
        message = await _answer(db, user_id=user_id, workspace_id=workspace_id, workflow_key=workflow_key)
        await _rate(
            db, message, user_id, rating, disliked="Missing detail." if rating == "bad" else None, aspects=aspects
        )
    other_message = await _answer(db, user_id=other_admin_id, workspace_id=other_id)
    await _rate(db, other_message, other_admin_id, "bad", disliked="Other Workspace only.")
    admin = await fetch_user(db, admin_id)

    async def listed(**filters):
        query = {"rating": None, "aspect": None, "workflow_key": None, "limit": 50, **filters}
        return (await list_workspace_feedback(workspace_id, **query, current_user=admin, db=db))["items"]

    assert len(await listed()) == 3
    assert {entry["workflow_key"] for entry in await listed(rating="bad")} == {"knowledge-request", "coding-change"}
    [by_aspect] = await listed(aspect="speed")
    assert (by_aspect["rating"], by_aspect["aspects"]) == ("bad", {"sources": "disliked", "speed": "liked"})
    assert by_aspect["session_link"] == f"/chat?session_id={by_aspect['session_id']}" and by_aspect["message_id"]
    assert by_aspect["memory_state"] == "confirmed"
    assert [entry["rating"] for entry in await listed(workflow_key="knowledge-request", rating="good")] == ["good"]
    assert "Other Workspace only." not in repr(await listed())

    summary = await summarize_workspace_feedback(
        workspace_id, rating=None, aspect=None, workflow_key=None, current_user=admin, db=db
    )
    assert (summary["total"], summary["good"], summary["bad"]) == (3, 1, 2)
    assert summary["by_workflow"] == [
        {"workflow_key": "coding-change", "bad": 1, "good": 0},
        {"workflow_key": "knowledge-request", "bad": 1, "good": 1},
    ]
    aspects = {entry["aspect"]: (entry["liked"], entry["disliked"]) for entry in summary["by_aspect"]}
    assert aspects["sources"] == (1, 1) and aspects["correctness"] == (0, 1) and aspects["clarity"] == (0, 0)
    filtered = await summarize_workspace_feedback(
        workspace_id, rating=None, aspect=None, workflow_key="coding-change", current_user=admin, db=db
    )
    assert (filtered["total"], filtered["bad"]) == (1, 1)

    with pytest.raises(HTTPException) as invalid:
        await listed(rating="Good")
    assert invalid.value.status_code == 422
    # A member of the Workspace needs the admin or owner role; another Workspace's admin sees nothing.
    with pytest.raises(HTTPException) as member:
        await list_workspace_feedback(
            workspace_id, None, None, None, 50, current_user=await fetch_user(db, member_id), db=db
        )
    assert member.value.status_code == 403
    with pytest.raises(HTTPException) as outsider:
        await summarize_workspace_feedback(
            workspace_id, None, None, None, current_user=await fetch_user(db, other_admin_id), db=db
        )
    assert outsider.value.status_code == 404
