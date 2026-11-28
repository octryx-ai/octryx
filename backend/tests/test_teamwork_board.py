"""The board wakes the coordinator while the items run; the team block tells each item who is who."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob
from app.services.agent_board.messages import Author, post_message
from app.services.agent_gateway.presence import session_key_hash
from app.services.agent_gateway.sessions import SESSION_KEY_METADATA
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from app.services.workflow_runs.records import new_chat_session
from app.services.workflow_runs.teamwork import coordinator
from app.services.workflow_runs.teamwork.team_block import team_block
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run

pytestmark = pytest.mark.usefixtures("scripted_pool")

ITEM_HASH = "b" * 24


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _split(db, *, at_parallel_work=True):
    admin, device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = list((await db.execute(select(DeviceJob).where(DeviceJob.session_id == thread.id))).scalars())
    gateway = await new_chat_session(db, admin, run.project_id)
    key = str(uuid.uuid4())
    gateway.metadata_ = {**dict(gateway.metadata_ or {}), SESSION_KEY_METADATA: key}
    context = {name: value for name, value in dict(run.context or {}).items() if name != CONTEXT_KEY}
    context["work"] = {"node_id": run.current_node_id if at_parallel_work else "elsewhere", "plan_node": "plan",
                       "coordinator_session_id": gateway.id, "route": None,
                       "items": {"api": {"id": "api", "role": "backend", "status": "running", "paths": ["server/**"],
                                         "agent_hash": ITEM_HASH},
                                 # Waits for api: no item starts, so no git work takes the main thread here.
                                 "ui": {"id": "ui", "role": "frontend", "status": "pending", "paths": ["web/**"],
                                        "depends_on": ["api"], "agent_hash": None}}}
    run.context = context
    await db.flush()
    return admin, device, thread, run, job, session_key_hash(key)


async def _ask(db, run, admin, to_hash, body="Which field name does the search API return?"):
    return await post_message(db, project_id=run.project_id, author=Author("agent", admin.id, ITEM_HASH),
                              arguments={"kind": "question", "body": body, "to_agent_hash": to_hash,
                                         "work_item_id": None})


async def _finish(db, job):
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})


@pytest.mark.asyncio
async def test_a_post_to_the_coordinator_waits_for_the_busy_main_thread_then_wakes_it_once(db):
    admin, _device, _thread, run, job, coordinator_hash = await _split(db)
    question = await _ask(db, run, admin, coordinator_hash)
    assert job.turn_count == 1
    assert run.context[coordinator.WAKE_KEY]["pending"] == [question.id]
    assert run.context["work"]["coordinator_hash"] == coordinator_hash

    await _finish(db, job)
    assert job.turn_count == 2 and job.status == "offered"
    assert question.id in job.turn_prompt and "board_post reply_to" in job.turn_prompt
    wake = run.context[coordinator.WAKE_KEY]
    assert (wake["pending"], wake["woken"], wake["job_id"]) == ([], [question.id], job.id)

    assert await coordinator.board_posted(db, question) is None
    assert job.turn_count == 2


@pytest.mark.asyncio
async def test_a_free_main_thread_wakes_at_once_and_a_later_question_rides_on_the_next_wake(db):
    admin, _device, _thread, run, job, coordinator_hash = await _split(db)
    await _finish(db, job)
    turns = job.turn_count
    first = await _ask(db, run, admin, coordinator_hash)
    assert job.turn_count == turns + 1 and first.id in job.turn_prompt
    second = await _ask(db, run, admin, coordinator_hash, body="And the test id?")
    assert job.turn_count == turns + 1
    await _finish(db, job)
    assert job.turn_count == turns + 2 and second.id in job.turn_prompt and first.id not in job.turn_prompt


@pytest.mark.asyncio
async def test_nothing_wakes_when_the_run_is_not_at_parallel_work_or_the_post_is_for_someone_else(db):
    admin, _device, _thread, run, job, coordinator_hash = await _split(db, at_parallel_work=False)
    await _finish(db, job)
    turns = job.turn_count
    await _ask(db, run, admin, coordinator_hash)
    assert job.turn_count == turns and coordinator.WAKE_KEY not in run.context

    admin, _device, _thread, run, job, _hash = await _split(db)
    await _finish(db, job)
    turns = job.turn_count
    await _ask(db, run, admin, "c" * 24)
    assert job.turn_count == turns and coordinator.WAKE_KEY not in run.context


@pytest.mark.asyncio
async def test_the_team_block_lists_the_coordinator_and_every_items_hash(db):
    _admin, _device, _thread, run, _job, coordinator_hash = await _split(db)
    block = await team_block(db, run, item_key="ui")
    assert block["coordinator"] == coordinator_hash
    assert [(item["id"], item["role"], item["agent_hash"], item.get("you", False)) for item in block["items"]] == [
        ("api", "backend", ITEM_HASH, False), ("ui", "frontend", None, True)]
    assert block["items"][0]["paths"] == ["server/**"]
    assert any(coordinator_hash in rule and "blocked" in rule for rule in block["rules"])
    run.context = {**run.context, "work": {}}
    assert await team_block(db, run) == {}
