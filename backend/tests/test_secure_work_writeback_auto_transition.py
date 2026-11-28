"""auto_transition_work_item names its outcome (status and reason), and the Jira action, failure/pause recording, coding start and PR delivery callers map that outcome."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import WorkItemWorkflowDefinition
from app.services.secure_work import lifecycle_transitions, workflow_mapping
from app.services.secure_work.lifecycle_transitions import auto_transition_work_item
from app.services.workflow_runs import action_failures, failure, pause
from app.services.workflow_runs.platform import jira
from app.services.workflow_runs.platform.dispatch import (
    CLASS_EXTERNAL,
    CLASS_SCOPE_MISMATCH,
    FAILED,
    SUCCEEDED,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.secure_work_writeback_scope_support import _definition, _item, connectors, world  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]


NOT_APPLIED = [
    {"status": "unchanged", "to_state": "blocked"},
    {"status": "skipped", "reason": "no_workflow_in_scope", "to_state": "blocked"},
    {"status": "skipped", "reason": "unknown_state", "to_state": "blocked"},
    {"status": "refused", "reason": "workflow_project_mismatch", "to_state": "blocked"},
    {"status": "skipped", "reason": "tracker_refused", "to_state": "blocked", "detail": "refused"},
]


ALL_RESULTS = [*NOT_APPLIED, {"status": "applied", "item_id": "i", "work_state": "development"}]


async def test_auto_transition_without_a_definition_in_scope_is_skipped_and_logged(world, connectors, caplog):  # noqa: F811
    await _definition(world, world.b)
    item = await _item(world, world.a)
    with caplog.at_level(logging.INFO, logger=lifecycle_transitions.__name__):
        result = await auto_transition_work_item(world.db, item=item, current_user=world.admin,
                                                 to_state="development", reason="probe")
    assert result == {"status": "skipped", "reason": "no_workflow_in_scope", "to_state": "development"}
    assert f"work_item_auto_transition_skipped source_key={item.source_key} reason=no_workflow_in_scope" in caplog.text
    assert connectors == [] and item.work_state == "intake"


async def test_an_item_already_in_the_state_is_unchanged_without_resolving(world, connectors, monkeypatch):  # noqa: F811
    resolved: list[str] = []

    async def _resolver(_db, item):
        resolved.append(item.id)

    monkeypatch.setattr(lifecycle_transitions, "default_workflow_for_item", _resolver)
    item = await _item(world, world.a, work_state="development")
    result = await auto_transition_work_item(world.db, item=item, current_user=world.admin,
                                             to_state="development", reason="probe")
    assert result == {"status": "unchanged", "to_state": "development"}
    run = SimpleNamespace(work_item_id=item.id, requested_by=world.admin.id, title="probe")
    outcome = await jira.transition(world.db, run, {"work_state": "development"})
    assert (outcome.state, outcome.result) == (SUCCEEDED, {"status": "unchanged", "work_state": "development"})
    assert resolved == [] and connectors == []


async def test_the_jira_transition_action_maps_every_result(world, connectors, monkeypatch):  # noqa: F811
    item = await _item(world, world.a)
    run = SimpleNamespace(work_item_id=item.id, requested_by=world.admin.id, title="probe")
    await _definition(world, world.b)
    missing = await jira.transition(world.db, run, {"work_state": "development"})
    # No write-back configured is not a failure; the run goes on and the step says Jira was left as is.
    assert (missing.state, missing.result["status"], missing.result["reason"]) == (
        SUCCEEDED, "skipped", "no_workflow_in_scope")
    assert "no write-back definition knows the Work state 'development'" in missing.result["note"]
    own = await _definition(world, world.a)
    unknown = await jira.transition(world.db, run, {"work_state": "no_such_state"})
    assert (unknown.state, unknown.result["status"], unknown.result["reason"]) == (
        SUCCEEDED, "skipped", "unknown_state")

    async def _foreign_default(_db, _item):
        return await _db.get(WorkItemWorkflowDefinition, (await _definition(world, world.b)).id)

    with monkeypatch.context() as patched:  # 10c: only a patched resolver can return a foreign definition
        patched.setattr(lifecycle_transitions, "default_workflow_for_item", _foreign_default)
        mismatch = await jira.transition(world.db, run, {"work_state": "development"})
    assert (mismatch.state, mismatch.failure_class) == (FAILED, CLASS_SCOPE_MISMATCH)
    assert mismatch.result == {"status": "refused", "reason": "workflow_project_mismatch", "to_state": "development"}
    assert CLASS_SCOPE_MISMATCH not in action_failures.RECOVERABLE
    assert "another Workspace" in action_failures._CLASS_TEXTS[CLASS_SCOPE_MISMATCH]
    assert connectors == [] and item.work_state == "intake"

    async def _jira_refuses(_db, *, item, workflow, preview):
        raise HTTPException(status_code=409, detail="Jira does not offer 'Start Progress'")

    monkeypatch.setattr(workflow_mapping, "execute_tracker_state_sync", _jira_refuses)
    refused = await jira.transition(world.db, run, {"work_state": "development"})
    assert (refused.state, refused.failure_class, refused.result["reason"]) == (
        FAILED, CLASS_EXTERNAL, "tracker_refused")
    assert "Start Progress" in refused.reason
    assert own.id and item.work_state == "intake"

    async def _jira_moved_meanwhile(_db, *, item, workflow, preview):
        raise HTTPException(status_code=409, detail="Jira changed after the Work Item was last synced")

    # A person or a Jira automation moved the issue since the last sync; their change
    # stands and the run goes on instead of failing the step.
    monkeypatch.setattr(workflow_mapping, "execute_tracker_state_sync", _jira_moved_meanwhile)
    moved = await jira.transition(world.db, run, {"work_state": "development"})
    assert (moved.state, moved.result["status"], moved.result["reason"]) == (
        SUCCEEDED, "skipped", "jira_changed_since_sync")


@pytest.mark.parametrize("outcome", NOT_APPLIED)
async def test_failure_and_pause_record_status_and_reason(world, monkeypatch, outcome):  # noqa: F811
    item = await _item(world, world.a)
    events: list[dict] = []

    async def _auto(_db, **_kwargs):
        return dict(outcome)

    def _record(_db, _run, _kind, **kwargs):
        events.append(kwargs["detail"])

    monkeypatch.setattr(lifecycle_transitions, "auto_transition_work_item", _auto)
    monkeypatch.setattr(failure, "record_event", _record)
    monkeypatch.setattr(pause, "record_event", _record)
    run = SimpleNamespace(id="run", work_item_id=item.id, parent_run_id=None, requested_by=world.admin.id,
                          title="probe", context={"stop": {"reason": "probe"}})
    await failure.outcome_work_state(world.db, run, outcome="blocked", config={})
    await pause._block_work_item(world.db, run, world.admin)
    assert [(event["result"], event["reason"]) for event in events] == [(outcome["status"], outcome.get("reason"))] * 2


