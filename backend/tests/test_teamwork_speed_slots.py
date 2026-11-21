"""The main thread's platform turns and the reviewer's seat call take no device slot, and review findings go to the item owning their file or to the coordinator."""

from __future__ import annotations

import pytest

from tests.teamwork_engine_support import fake, finish_item, items_of  # noqa: F401  (``fake`` is a fixture)
from tests.test_team_delivery import _story_at_work, actions  # noqa: F401  (``actions`` is a fixture)

# --- the review's findings become fix items too ---------------------------------------------------------------------


async def _review_changes(db, run, findings: list[dict], *, auto: bool = True) -> None:
    from app.services.workflow_runs.engine import resolve_current_node

    run.status, run.current_node_id = "running", "decisions"
    answer = {"text": "Revise: the review found high findings.", "by": None, "at": "2026-11-13T13:40:00",
              **({"auto_revision": 1} if auto else {})}
    run.context = {**run.context, "review": {"verdict": "changes", "summary": "two points", "findings": findings},
                   "po_answers": [*(run.context.get("po_answers") or []), answer]}
    await resolve_current_node(db, run, "changed", actor_id=None)


# --- device slots ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_main_threads_platform_turns_take_no_slot_and_items_get_every_slot(db):
    """With four slots, four items run at once: the scheduler keeps no slot for the main thread."""
    from app.models import UserDevice
    from app.services.devices.dispatch_gate import check_device_dispatch
    from app.services.devices.job_offer import offer_body
    from app.services.devices.jobs import counted_job_count, start_turn
    from app.services.workflow_runs.records import new_chat_session
    from app.services.workflow_runs.teamwork import device_items
    from app.services.workflow_runs.teamwork.slots import slot_free
    from tests.teamwork_device_support import FOLDER, _run

    admin, device, thread, run = await _run(db, slots=2)
    assert (await device_items.executor_for(db, run)).capacity(run) == 2  # every slot runs an item

    for _ in range(2):  # two items fill both slots
        other = await new_chat_session(db, admin, thread.project_id)
        await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                         session_id=other.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                         prompt="an item's turn")
    assert await counted_job_count(db, device.id) == 2
    busy = await check_device_dispatch(db, user_id=admin.id, thread_owner_id=admin.id, device_id=device.id,
                                       folder=FOLDER, profile="governed", workspace_id=thread.project_id,
                                       session_id=(await new_chat_session(db, admin, thread.project_id)).id)
    assert (busy.allowed, busy.reason) == (False, "device_busy")
    git = await check_device_dispatch(db, user_id=admin.id, thread_owner_id=admin.id, device_id=device.id,
                                      folder=FOLDER, profile="governed", workspace_id=thread.project_id,
                                      session_id=thread.id)
    assert git.allowed  # the run's git work never waits behind its items
    job = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                           session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                           prompt="Platform git work")
    assert await counted_job_count(db, device.id) == 2  # and takes no slot
    assert offer_body(job, limits={}, slot_exempt=await slot_free(db, thread.id))["slot_exempt"] is True
    run.current_node_id = "pipeline"  # once the run left the team node, its main thread counts again
    assert await counted_job_count(db, device.id) == 3 and not await slot_free(db, thread.id)


@pytest.mark.asyncio
async def test_a_high_review_finding_goes_to_the_item_owning_its_file(db, fake, actions):  # noqa: F811
    """High findings (flat cards, a missing icon circle, a toast's language) must not each go through a
    coordinator round that costs far more than the fix."""
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_marker import RUN_PHASE_CONTRACT_KEY
    from app.services.workflow_runs.teamwork.item_definition import item_definition

    run, _session, _plan = await _story_at_work(db, fake)
    for name in ("api", "ui"):
        await finish_item(db, run, name)
    started = len(fake.started)
    await _review_changes(db, run, [
        {"severity": "high", "file": "web/cards.css", "line": 12, "fix": "Cards use the gradient token."},
        {"severity": "low", "file": "server/api.py", "line": 3, "fix": "Name the constant."}])

    assert run.current_node_id == "work"
    items = items_of(run)
    assert (items["ui"]["status"], items["ui"]["iteration"]) == ("running", 2)
    assert (items["api"]["status"], items["api"]["iteration"]) == ("merged", 1)  # a low finding is a note
    assert [name for name, _ in fake.started[started:]] == ["ui"]
    node = (await graph_for_run(db, run)).nodes["work"]
    facts = item_definition(run, node, items["ui"])["workflow_contract"][RUN_PHASE_CONTRACT_KEY]
    assert facts["review_fix"]["findings"] == [
        {"what": "review finding web/cards.css:12 [high] Cards use the gradient token."}]
    await finish_item(db, run, "ui")
    assert run.current_node_id == "pipeline"


@pytest.mark.asyncio
async def test_a_persons_answer_or_a_finding_no_item_owns_goes_to_the_coordinator(db, fake, actions):  # noqa: F811
    run, _session, _plan = await _story_at_work(db, fake)
    for name in ("api", "ui"):
        await finish_item(db, run, name)
    await _review_changes(db, run, [{"severity": "high", "file": "web/cards.css", "line": 1, "fix": "x"}], auto=False)
    assert run.current_node_id == "plan"
    assert {key: item["status"] for key, item in items_of(run).items()} == {"api": "merged", "ui": "merged"}


@pytest.mark.asyncio
async def test_the_reviewers_seat_call_never_waits_for_a_slot(db):
    """When the device's slots are taken (another epic's story and the run's finishing draft turn), the reviewer's
    seat call must not be refused ``device_busy``, fall back to a company runtime without the model and pause
    ``review_model_not_admitted``. Its thread is slot free."""
    from app.models import Session, UserDevice
    from app.services.devices.dispatch_gate import check_device_dispatch
    from app.services.devices.jobs import counted_job_count, start_turn
    from app.services.workflow_runs.records import new_chat_session
    from app.services.workflow_runs.review.seat import PURPOSE_KEY, REVIEW_PURPOSE
    from app.services.workflow_runs.teamwork.slots import slot_free
    from tests.teamwork_device_support import FOLDER, _run

    admin, device, thread, _run_row = await _run(db, slots=1)
    other = await new_chat_session(db, admin, thread.project_id)
    await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id), session_id=other.id,
                     workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="a story's turn")
    review = Session(user_id=admin.id, project_id=thread.project_id, status="active", origin="chat",
                     metadata_={PURPOSE_KEY: REVIEW_PURPOSE, "title": "Independent review"})
    db.add(review)
    await db.flush()
    assert await slot_free(db, review.id) and not await slot_free(db, other.id)
    allowed = await check_device_dispatch(db, user_id=admin.id, thread_owner_id=admin.id, device_id=device.id,
                                          folder=FOLDER, profile="governed", workspace_id=thread.project_id,
                                          session_id=review.id)
    assert allowed.allowed
    await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id), session_id=review.id,
                     workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="review")
    assert await counted_job_count(db, device.id) == 1  # the review takes no slot
