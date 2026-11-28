"""The main thread's platform turns and the reviewer's seat call take no device slot, and review findings go to the item owning their file or to the coordinator."""

from __future__ import annotations

import pytest

from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.teamwork_engine_support import fake, finish_item, items_of  # noqa: F401  (``fake`` is a fixture)
from tests.test_team_delivery import _story_at_work, actions  # noqa: F401  (``actions`` is a fixture)

pytestmark = pytest.mark.usefixtures("scripted_pool")




@pytest.mark.asyncio
async def test_the_main_threads_platform_turns_take_no_slot_and_items_get_every_slot(db):
    from app.models import UserDevice
    from app.services.devices.dispatch_gate import check_device_dispatch
    from app.services.devices.job_offer import offer_body
    from app.services.devices.jobs import counted_job_count, start_turn
    from app.services.workflow_runs.records import new_chat_session
    from app.services.workflow_runs.teamwork import device_items
    from app.services.workflow_runs.teamwork.slots import slot_free
    from tests.teamwork_device_support import FOLDER, _run

    admin, device, thread, run = await _run(db, slots=2)
    assert (await device_items.executor_for(db, run)).capacity(run) == 2

    for _ in range(2):
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
    assert git.allowed
    job = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                           session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                           prompt="Platform git work")
    assert await counted_job_count(db, device.id) == 2
    assert offer_body(job, limits={}, slot_exempt=await slot_free(db, thread.id))["slot_exempt"] is True
    run.current_node_id = "pipeline"
    assert await counted_job_count(db, device.id) == 3 and not await slot_free(db, thread.id)






@pytest.mark.asyncio
async def test_the_reviewers_seat_call_never_waits_for_a_slot(db):
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
    assert await counted_job_count(db, device.id) == 1
