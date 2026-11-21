"""A workflow run's main chat thread is listed under the run's work item ("<key> <title>"), not its first prompt.

Contract: binding the main thread names it after the work item (or the run title without one); a title the user
gave is never replaced, and the device's continuation prompt does not rename the thread afterwards.
"""

from __future__ import annotations

import pytest

from app.models import WorkItem
from app.services.devices.hub import device_hub
from app.services.session.session_title import apply_prompt_title, apply_user_title
from app.services.workflow_runs.records import bind_session, new_chat_session
from tests.workflow_run_octryx_continuation_support import _device_run


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


@pytest.mark.asyncio
async def test_the_main_thread_is_named_after_the_work_item_and_a_user_title_stays(db):
    admin, _device, thread, run = await _device_run(db)
    assert thread.metadata_["title"] == run.title and thread.metadata_["title_source"] == "run"

    item = WorkItem(source_type="jira", source_instance="t", source_key="BRD-14", title="Add capitalize_words",
                    project_id=run.project_id)
    db.add(item)
    await db.flush()
    run.work_item_id = item.id
    named = await new_chat_session(db, admin, run.project_id)
    await bind_session(db, run, named)
    assert named.metadata_["title"] == "BRD-14 Add capitalize_words"
    metadata = dict(named.metadata_)
    apply_prompt_title(metadata, "Continue workflow run feature-delivery-tdd: phase 'Clarify'")
    assert metadata["title"] == "BRD-14 Add capitalize_words"  # the continuation prompt does not rename it

    renamed = await new_chat_session(db, admin, run.project_id)
    metadata = dict(renamed.metadata_ or {})
    apply_user_title(metadata, "My payments work")
    renamed.metadata_ = metadata
    await bind_session(db, run, renamed)
    assert renamed.metadata_["title"] == "My payments work"
