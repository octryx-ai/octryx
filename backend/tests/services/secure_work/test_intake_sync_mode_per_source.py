"""The write-back mode belongs to the intake source."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkItemSyncConfig, WorkItemWorkflowDefinition
from app.services.secure_work.jira.jira_state_sync import execute_jira_state_sync, will_write_jira
from app.services.secure_work.sync_policy import executes
from app.services.secure_work.tracker_drivers import execute_tracker_state_sync
from app.services.secure_work.work_item_close import close_preview
from app.services.secure_work.workflow_mapping import _normalize_sync_policy

SYNC_PREVIEW = {"sync_back": True, "target_status": "Done"}


async def _world(db, *, workflow_mode: str, intake_mode: str | None, source_type: str = "jira") -> SimpleNamespace:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"mode-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    config = WorkItemSyncConfig(name="intake", project_id=project.id, source_type=source_type,
                                sync_options_json={"sync_mode": intake_mode} if intake_mode else {},
                                created_by=admin.id)
    workflow = WorkItemWorkflowDefinition(
        name="flow", project_id=project.id, states_json=[], is_default=True, is_active=True,
        mappings_json={"done": {"source_status": "Done", "sync_back": True}},
        sync_policy_json=_normalize_sync_policy({"sync_mode": workflow_mode}), created_by=admin.id)
    db.add_all([config, workflow])
    await db.flush()
    item = WorkItem(project_id=project.id, sync_config_id=config.id, source_type=source_type,
                    source_instance="default", source_key=f"OCX-{uuid.uuid4().hex[:6]}", title="t",
                    work_state="development", sync_state="imported")
    db.add(item)
    await db.commit()
    return SimpleNamespace(config=config, workflow=workflow, item=item)


@pytest.mark.parametrize(("workflow_mode", "intake_mode", "writes"), [
    ("execute", "dry_run_only", False),  # the intake only previews although the workflow executes
    ("dry_run_only", "execute", True),  # the intake writes back although the workflow only previews
    ("execute", None, True),  # no own mode: the workflow's is the default
    ("dry_run_only", None, False),
])
async def test_the_intakes_own_mode_overrides_the_workflow_default_for_jira(db, workflow_mode, intake_mode, writes):
    world = await _world(db, workflow_mode=workflow_mode, intake_mode=intake_mode)
    assert will_write_jira(world.item, world.workflow, SYNC_PREVIEW) is writes
    expected = None if writes else "write_back_disabled"
    assert (await close_preview(db, world.item))["write_back_reason"] == expected


async def test_the_intake_is_read_even_when_it_is_not_loaded_yet(db):
    world = await _world(db, workflow_mode="execute", intake_mode="dry_run_only")
    db.expunge(world.config)
    assert (await close_preview(db, world.item))["write_back_reason"] == "write_back_disabled"


async def test_the_jira_driver_writes_nothing_for_a_dry_run_intake(db):
    world = await _world(db, workflow_mode="execute", intake_mode="dry_run_only")
    # Any Jira access would need a connection this world does not have: None means the gate held.
    preview = {"jira_sync_preview": {**SYNC_PREVIEW, "transition": "Done"}}
    assert await execute_jira_state_sync(db, item=world.item, workflow=world.workflow, preview=preview) is None


@pytest.mark.parametrize(("workflow_mode", "intake_mode", "result"), [
    ("execute", "dry_run_only", None),
    ("dry_run_only", "execute", {"status": "no_driver", "source_type": "servicenow"}),
])
async def test_a_source_without_a_driver_reports_its_gap_only_where_its_mode_writes(db, workflow_mode, intake_mode,
                                                                                    result):
    world = await _world(db, workflow_mode=workflow_mode, intake_mode=intake_mode, source_type="servicenow")
    preview = {"jira_sync_preview": SYNC_PREVIEW}
    assert await execute_tracker_state_sync(db, item=world.item, workflow=world.workflow, preview=preview) == result


def test_only_sync_mode_decides_and_saving_writes_it_alone():
    assert executes({"sync_mode": "execute"}) is True
    assert executes({"jira_sync_mode": "execute"}) is False, "a source-specific name decides nothing"
    for given, mode in [({"sync_mode": "execute"}, "execute"), ({"sync_mode": "dry_run_only"}, "dry_run_only"),
                        ({"jira_sync_mode": "execute"}, "dry_run_only"), (None, "dry_run_only")]:
        saved = _normalize_sync_policy(given)
        assert saved["sync_mode"] == mode, given
        assert "mutates_jira" not in saved and executes(saved) is (mode == "execute")


def test_the_overview_names_the_workflow_default_next_to_the_sources_own_mode():
    from types import SimpleNamespace

    from app.services.secure_work.intake.setup import sync_mode_of

    own = SimpleNamespace(sync_options_json={"sync_mode": "execute"})
    follows = SimpleNamespace(sync_options_json={})
    policy = {"sync_mode": "dry_run_only"}
    assert sync_mode_of(own, policy) == {"own": "execute", "workflow": "dry_run_only", "effective": "execute"}
    assert sync_mode_of(follows, policy) == {"own": None, "workflow": "dry_run_only", "effective": "dry_run_only"}
