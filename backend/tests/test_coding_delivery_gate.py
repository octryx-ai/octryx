from __future__ import annotations

from types import SimpleNamespace

from app.models import Session as ChatSession
from app.models import ToolCall, User
from app.services.coding_delivery_gate import enforce_coding_delivery_validation

GOVERNED_METADATA = {
    "secure_work_execution": {
        "verification_contract": {"commands": [{"command": "grep ...", "source": "change_unit"}]}
    }
}


async def _session(db, *, metadata) -> ChatSession:
    user = (
        User(username=f"gate-user-{id(metadata)}", email=f"gate-{id(metadata)}@example.test", password_hash="x")
    )
    db.add(user)
    await db.flush()
    session = ChatSession(user_id=user.id, metadata_=metadata)
    db.add(session)
    await db.flush()
    return session


def _validation_call(session_id: str, *, all_green: bool) -> ToolCall:
    return ToolCall(
        session_id=session_id,
        tool_name="run_validation_commands",
        parameters={},
        result={"all_green": all_green, "results": []},
        status="success",
    )


async def test_delivery_blocked_without_validation(db):
    session = await _session(db, metadata=GOVERNED_METADATA)
    context = SimpleNamespace(db=db, session_id=session.id)
    for tool in ("commit_and_push_repository_branch", "create_bitbucket_pull_request", "add_jira_comment"):
        blocked = await enforce_coding_delivery_validation(tool, context)
        assert blocked is not None, tool
        assert blocked["status"] == "needs_validation"


async def test_delivery_allowed_after_all_green(db):
    session = await _session(db, metadata=GOVERNED_METADATA)
    db.add(_validation_call(session.id, all_green=True))
    await db.flush()
    context = SimpleNamespace(db=db, session_id=session.id)
    assert await enforce_coding_delivery_validation("add_jira_comment", context) is None


async def test_latest_red_validation_blocks_again(db):
    session = await _session(db, metadata=GOVERNED_METADATA)
    db.add(_validation_call(session.id, all_green=True))
    await db.flush()
    db.add(_validation_call(session.id, all_green=False))
    await db.flush()
    context = SimpleNamespace(db=db, session_id=session.id)
    blocked = await enforce_coding_delivery_validation("commit_and_push_repository_branch", context)
    assert blocked is not None and blocked["status"] == "needs_validation"


async def test_non_governed_sessions_and_non_delivery_tools_pass(db):
    session = await _session(db, metadata={})
    context = SimpleNamespace(db=db, session_id=session.id)
    assert await enforce_coding_delivery_validation("add_jira_comment", context) is None
    governed = await _session(db, metadata=GOVERNED_METADATA)
    governed_context = SimpleNamespace(db=db, session_id=governed.id)
    assert await enforce_coding_delivery_validation("read_workspace_file", governed_context) is None


async def test_step_advance_into_delivery_requires_all_green(db):
    from app.services.coding_delivery_gate import delivery_step_advance_blocked

    session = await _session(db, metadata=GOVERNED_METADATA)
    delivery_tools = {"get_git_diff", "commit_and_push_repository_branch", "add_jira_comment"}
    # no validation yet -> blocked
    assert await delivery_step_advance_blocked(
        db, session_id=session.id, source_step_type="tdd_cycle", target_allowed_tools=delivery_tools
    )
    # non-tdd source or non-delivery target -> not this gate's business
    assert not await delivery_step_advance_blocked(
        db, session_id=session.id, source_step_type="analysis", target_allowed_tools=delivery_tools
    )
    assert not await delivery_step_advance_blocked(
        db, session_id=session.id, source_step_type="tdd_cycle", target_allowed_tools={"read_workspace_file"}
    )
    # all_green -> advance allowed
    db.add(_validation_call(session.id, all_green=True))
    await db.flush()
    assert not await delivery_step_advance_blocked(
        db, session_id=session.id, source_step_type="tdd_cycle", target_allowed_tools=delivery_tools
    )
