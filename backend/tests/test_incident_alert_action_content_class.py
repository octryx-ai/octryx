"""A content-policy refusal is a permanent, typed refusal: terminal at once, never scheduled for retry, classified by provenance rather than error text, and recorded as its closed class on the failed trace."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.runtime.runtime_errors import RUNTIME_ERROR_CONTENT_POLICY_DENIED
from app.models import TaskRun, User
from app.services.circuit_breaker import escalate_failed_task_run_decision
from app.services.content_security.refusal import (
    TURN_ERROR_CONTENT_BLOCKED,
    ContentPolicyRefusedError,
    recorded_turn_error_class,
    turn_error_class,
    with_turn_error_class,
)

BLOCK_TEXT = "Content policy refused the request: platform:prompt-injection-refused"


# --- B1: typed classification -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_content_refusal_is_terminal_and_never_scheduled_for_retry(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    from app.models import Task

    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), name="t", task_type="agent_run", owner_id=admin.id, is_active=True, config={})
    task_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, trigger_type="webhook", status="error",
                       started_by=admin.id, input_={})
    db.add_all([task, task_run])
    await db.flush()

    row, decision = await escalate_failed_task_run_decision(
        db, task_id=task.id, task_run_id=task_run.id, error="content_blocked", trigger_id=None, content_blocked=True)

    assert row.status == decision.status == "content_blocked"
    assert decision.retryable is False and decision.terminal is True
    assert decision.retry_delay_seconds is None and row.next_retry_at is None
    assert decision.reason == "agent_turn_content_blocked"
    assert decision.retry_policy == "content_blocked" and decision.max_retry_attempts == 0


def test_the_class_is_typed_provenance_never_the_error_text():
    exc = ContentPolicyRefusedError(("platform:prompt-injection-refused",), {"kind": "block"})
    assert exc.runtime_error_class == RUNTIME_ERROR_CONTENT_POLICY_DENIED and str(exc) == BLOCK_TEXT
    assert recorded_turn_error_class(with_turn_error_class({"error": str(exc)}, exc)) == TURN_ERROR_CONTENT_BLOCKED
    # The runtime chain's own error carries the refusal as a typed attempt (any content refusal, any driver).
    chain = RuntimeError("All configured runtime targets failed")
    chain.runtime_attempts = [{"status": "error", "error_class": RUNTIME_ERROR_CONTENT_POLICY_DENIED}]
    assert turn_error_class(chain) == TURN_ERROR_CONTENT_BLOCKED
    # The same words from any other exception, or a forged class without an error, classify as nothing.
    plain = RuntimeError(BLOCK_TEXT)
    assert recorded_turn_error_class(with_turn_error_class({"error": str(plain)}, plain)) is None
    assert recorded_turn_error_class({"error_class": TURN_ERROR_CONTENT_BLOCKED}) is None
    assert recorded_turn_error_class({"error": "x", "error_class": "something_else"}) is None


