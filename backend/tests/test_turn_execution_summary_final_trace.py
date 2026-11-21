"""The final trace aggregates the whole turn; intermediate, unmarked, stalled or suppressed traces are never finished."""

import json
import uuid

import pytest

from app.models import Approval, Session, ToolCall, TurnTrace
from app.models.runtime.artifact_store import ToolArtifact
from tests.turn_execution_summary_api_support import (
    SECRET,
    _admin,
    _allowed_snapshot,
    _session,
    _summary,
    _trace,
    _user_message,
)


async def _approval_tool_call(db, session: Session, trace: TurnTrace, tool_name: str, *, admin_id: str) -> Approval:
    approval = Approval(
        id=str(uuid.uuid4()),
        session_id=session.id,
        requested_by=admin_id,
        action=f"{tool_name} --token {SECRET}",
        status="pending",
    )
    db.add(approval)
    tool_call_id = str(uuid.uuid4())
    db.add(
        ToolCall(
            id=tool_call_id,
            session_id=session.id,
            message_id=trace.message_id,
            tool_name=tool_name,
            parameters={"token": SECRET},
            result={"approval_required": True, "approval_status": "pending", "approval_id": approval.id},
            status="success",
        )
    )
    db.add(
        ToolArtifact(
            id=tool_call_id,
            session_id=session.id,
            message_id=trace.message_id,
            tool_name=tool_name,
            relative_path=f"{session.id}/{tool_call_id}.json.gz",
            content_sha256="b" * 64,
            payload_size_bytes=2048,
            preview_json={"compact_result": {"secret": SECRET}},
        )
    )
    await db.flush()
    return approval


@pytest.mark.asyncio
async def test_final_trace_aggregates_the_whole_turn_and_intermediate_trace_stays_neutral(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    other_session = await _session(db, admin.id)

    # An earlier turn in the same session with its own capability must not leak in.
    earlier_user = await _user_message(db, session, "earlier question")
    earlier = await _trace(db, session, snapshot=_allowed_snapshot(user_message_id=earlier_user.id, finished=True))
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=session.id,
            message_id=earlier.message_id,
            tool_name="earlier_tool",
            parameters={},
            result={},
            status="success",
        )
    )

    user = await _user_message(db, session)
    tool_only = await _trace(db, session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=0))
    approval = await _approval_tool_call(db, session, tool_only, "terraform_apply", admin_id=admin.id)
    final = await _trace(
        db, session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=1, finished=True)
    )

    # Same token in a different session (cannot happen at runtime) must stay isolated.
    foreign = await _trace(db, other_session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=2))
    db.add(
        ToolCall(
            id=str(uuid.uuid4()),
            session_id=other_session.id,
            message_id=foreign.message_id,
            tool_name="foreign_tool",
            parameters={},
            result={},
            status="success",
        )
    )
    await db.flush()

    summary = await _summary(db, admin.id, final)
    assert summary["state"] == "waiting_approval"
    assert summary["next_action"]["kind"] == "resolve_approval"
    assert summary["capabilities_used"] == [{"name": "terraform_apply", "calls": 1, "succeeded": 1, "failed": 0}]
    assert [item["approval_id"] for item in summary["approvals"]] == [approval.id]
    assert [item["tool_name"] for item in summary["artifacts"]] == ["terraform_apply"]
    assert summary["usage"] == {"tokens_in": 6, "tokens_out": 8}
    assert SECRET not in json.dumps(summary)

    intermediate = await _summary(db, admin.id, tool_only)
    assert intermediate["state"] == "unknown"
    assert intermediate["state_reason"]["code"] == "intermediate_trace"
    assert intermediate["capabilities_used"][0]["name"] == "terraform_apply"
    assert intermediate["usage"] == {"tokens_in": 3, "tokens_out": 4}

    # Once the approval is decided, the explicitly finished turn is unverified,
    # and the intermediate trace still never claims a terminal state.
    approval.status = "approved"
    await db.flush()
    assert (await _summary(db, admin.id, final))["state"] == "finished_unverified"
    assert (await _summary(db, admin.id, tool_only))["state"] != "finished_unverified"

    earlier_summary = await _summary(db, admin.id, earlier)
    assert [item["name"] for item in earlier_summary["capabilities_used"]] == ["earlier_tool"]
    assert earlier_summary["state"] == "finished_unverified"
    foreign_summary = await _summary(db, admin.id, foreign)
    assert [item["name"] for item in foreign_summary["capabilities_used"]] == ["foreign_tool"]
    assert foreign_summary["approvals"] == []


@pytest.mark.asyncio
async def test_final_trace_without_explicit_marker_is_unknown(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    user = await _user_message(db, session)
    await _trace(db, session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=0))
    final = await _trace(
        db,
        session,
        snapshot=_allowed_snapshot(user_message_id=user.id, sequence=1),
        raw_output={"content": "All tasks completed successfully!"},
    )
    summary = await _summary(db, admin.id, final)
    assert summary["state"] == "unknown"
    assert summary["state_reason"]["code"] == "runtime_outcome_unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_output",
    [
        {"content": "Stopped.", "stalled_after_tool_loop": True},
        {"content": "Blocked.", "suppressed_as_duplicate_no_tool_response": True},
    ],
)
async def test_known_stall_or_suppressed_final_trace_is_never_finished(db, raw_output):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    user = await _user_message(db, session)
    final = await _trace(db, session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=0),
                         raw_output=raw_output)
    assert (await _summary(db, admin.id, final))["state"] == "unknown"


@pytest.mark.asyncio
async def test_failure_marker_on_an_intermediate_trace_is_not_terminal(db):
    admin = await _admin(db)
    session = await _session(db, admin.id)
    user = await _user_message(db, session)
    early = await _trace(
        db,
        session,
        snapshot=_allowed_snapshot(user_message_id=user.id, sequence=0),
        raw_output={"error": f"boom {SECRET}"},
    )
    final = await _trace(db, session, snapshot=_allowed_snapshot(user_message_id=user.id, sequence=1),
                         raw_output={"error": "later failure"})
    assert (await _summary(db, admin.id, early))["state_reason"]["code"] == "intermediate_trace"
    assert (await _summary(db, admin.id, final))["state"] == "failed"
