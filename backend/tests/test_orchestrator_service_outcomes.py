"""Orchestrator run outcomes: child outputs merge and conflicts resolve, reviewer-critic reviews pass, fail or hit the iteration cap, runs complete or cancel, and the terminal check follows the run and its children."""

import uuid

import pytest

from app.models import Session
from app.models.agent.orchestrator_agent import (
    ORCHESTRATOR_PATTERN_PARALLEL,
    ORCHESTRATOR_PATTERN_REVIEWER_CRITIC,
    ORCHESTRATOR_PATTERN_SINGLE,
    ORCHESTRATOR_PATTERN_SUPERVISOR,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_RUNNING,
)
from app.services.orchestrator_service import (
    cancel_orchestrator_run,
    complete_orchestrator_run,
    create_orchestrator_run,
    is_orchestrator_terminal,
    merge_child_output,
    resolve_conflict,
    submit_review,
)


@pytest.mark.asyncio
async def test_merge_child_output_append(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_PARALLEL)
    await db.commit()
    await merge_child_output(db, run, "child-1", {"result": "output-1"}, merge_strategy="append")
    await merge_child_output(db, run, "child-2", {"result": "output-2"}, merge_strategy="append")
    await db.commit()

    merged = run.merged_output_json
    assert "children" in merged
    assert len(merged["children"]) == 2
    assert merged["children"][0]["child_session_id"] == "child-1"


@pytest.mark.asyncio
async def test_merge_child_output_replace(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    await merge_child_output(db, run, "child-1", {"data": "v1"}, merge_strategy="replace")
    await merge_child_output(db, run, "child-1", {"data": "v2"}, merge_strategy="replace")
    await db.commit()
    assert run.merged_output_json["child-1"]["data"] == "v2"


@pytest.mark.asyncio
async def test_resolve_conflict(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR)
    await db.commit()
    await resolve_conflict(db, run, "conflict-1", {"winner": "child-2"}, winner_session_id="child-2", notes="child-2 is better")
    await db.commit()
    assert len(run.conflict_resolutions_json) == 1
    assert run.conflict_resolutions_json[0]["conflict_key"] == "conflict-1"
    assert run.conflict_resolutions_json[0]["winner_session_id"] == "child-2"


@pytest.mark.asyncio
async def test_submit_review_reviewer_critic_pass(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_REVIEWER_CRITIC)
    await db.commit()
    await submit_review(db, run, "pass", notes="Looks good")
    await db.commit()
    assert run.status == ORCHESTRATOR_STATUS_COMPLETED
    assert run.last_review_score == "pass"
    assert run.revision_count == 1


@pytest.mark.asyncio
async def test_submit_review_reviewer_critic_fail(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_REVIEWER_CRITIC)
    await db.commit()
    await submit_review(db, run, "fail", notes="Needs work")
    await db.commit()
    assert run.status == ORCHESTRATOR_STATUS_RUNNING  # agent should revise
    assert run.revision_count == 1


@pytest.mark.asyncio
async def test_submit_review_reviewer_critic_max_iterations(db):
    """reviewer_critic: max iterations is NOT enforced as failure — only evaluator_optimizer caps out."""
    run = await create_orchestrator_run(
        db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_REVIEWER_CRITIC, max_iterations=2
    )
    await db.commit()
    await submit_review(db, run, "fail")  # rev 1
    await db.commit()
    await submit_review(db, run, "fail")  # rev 2 — reviewer_critic keeps running
    await db.commit()
    assert run.status == ORCHESTRATOR_STATUS_RUNNING
    assert run.revision_count == 2


@pytest.mark.asyncio
async def test_complete_orchestrator_run(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR)
    await db.commit()
    await complete_orchestrator_run(db, run, final_output={"summary": "Done"}, error=None)
    await db.commit()
    assert run.status == ORCHESTRATOR_STATUS_COMPLETED
    assert run.completed_at is not None
    assert run.merged_output_json.get("final", {}).get("summary") == "Done"


@pytest.mark.asyncio
async def test_complete_orchestrator_run_invalid_status(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    with pytest.raises(ValueError, match="Invalid status"):
        await complete_orchestrator_run(db, run, status="invalid_status")


@pytest.mark.asyncio
async def test_cancel_orchestrator_run(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR)
    await db.commit()
    await cancel_orchestrator_run(db, run, error="User cancelled")
    await db.commit()
    assert run.status == "cancelled"
    assert run.last_error == "User cancelled"


@pytest.mark.asyncio
async def test_is_orchestrator_terminal_completed(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SINGLE)
    await db.commit()
    await complete_orchestrator_run(db, run)
    await db.commit()
    assert await is_orchestrator_terminal(db, run) is True


@pytest.mark.asyncio
async def test_is_orchestrator_terminal_running(db):
    run = await create_orchestrator_run(db, session_id="s1", pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR)
    await db.commit()
    assert await is_orchestrator_terminal(db, run) is False


@pytest.mark.asyncio
async def test_is_orchestrator_terminal_all_children_done(db):
    # Create parent session
    parent_session = Session(
        id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={}
    )
    db.add(parent_session)

    # Create two child sessions both completed
    child1 = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="completed", metadata_={})
    child2 = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="completed", metadata_={})
    db.add(child1)
    db.add(child2)

    run = await create_orchestrator_run(
        db,
        session_id=parent_session.id,
        pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR,
        child_session_ids=[child1.id, child2.id],
    )
    await db.flush()

    assert await is_orchestrator_terminal(db, run) is True


@pytest.mark.asyncio
async def test_is_orchestrator_terminal_children_pending(db):
    parent_session = Session(
        id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={}
    )
    db.add(parent_session)
    child1 = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="completed", metadata_={})
    child2 = Session(id=str(uuid.uuid4()), user_id="u1", agent_type="change", status="active", metadata_={})
    db.add(child1)
    db.add(child2)

    run = await create_orchestrator_run(
        db,
        session_id=parent_session.id,
        pattern_type=ORCHESTRATOR_PATTERN_SUPERVISOR,
        child_session_ids=[child1.id, child2.id],
    )
    await db.flush()

    assert await is_orchestrator_terminal(db, run) is False
