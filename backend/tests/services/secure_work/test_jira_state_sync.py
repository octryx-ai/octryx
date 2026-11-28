from __future__ import annotations

from app.services.secure_work.jira.jira_state_sync import resolve_transition
from app.services.secure_work.sync_policy import executes
from app.services.secure_work.workflow_mapping import _normalize_sync_policy

AVAILABLE = [
    {"id": "5", "name": "Resolve Issue", "to": {"name": "Resolved"}},
    {"id": "751", "name": "Start Analyzing", "to": {"name": "In Analysis"}},
    {"id": "821", "name": "Ready for Development", "to": {"name": "Open"}},
]


def test_resolve_by_transition_name_case_insensitive():
    match = resolve_transition(AVAILABLE, jira_transition="ready for development", jira_status=None)
    assert match and match["id"] == "821"


def test_resolve_by_target_status_when_name_missing():
    match = resolve_transition(AVAILABLE, jira_transition=None, jira_status="In Analysis")
    assert match and match["id"] == "751"


def test_unreachable_transition_resolves_to_none():
    assert resolve_transition(AVAILABLE, jira_transition="Start Development", jira_status="In Development") is None
    assert resolve_transition(AVAILABLE, jira_transition=None, jira_status=None) is None


def test_sync_policy_execute_is_explicit_opt_in():
    assert executes(_normalize_sync_policy(None)) is False
    assert executes(_normalize_sync_policy({"sync_mode": "dry_run_only"})) is False
    assert executes(_normalize_sync_policy({"sync_mode": "execute"})) is True


async def test_auto_transition_without_workflow_is_a_noop(db):
    from types import SimpleNamespace

    from app.models import User, WorkItem
    from app.services.secure_work.lifecycle_transitions import auto_transition_work_item

    user = User(username="lifecycle-user", email="lifecycle@example.test", password_hash="x")
    db.add(user)
    item = WorkItem(
        source_type="jira",
        source_instance="lifecycle-test",
        source_key="OCX-LC-1",
        title="Lifecycle test",
        source_status="Requested",
        work_state="intake",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    result = await auto_transition_work_item(
        db, item=item, current_user=user, to_state="development", reason="agent started"
    )
    assert (result["status"], result["reason"]) == ("skipped", "no_workflow_in_scope")
    assert item.work_state == "intake"
    _ = SimpleNamespace  # keep import for symmetry with sibling tests


async def test_auto_transition_applies_locally_with_dry_run_workflow(db):
    from app.models import User, WorkItem, WorkItemWorkflowDefinition
    from app.services.secure_work.lifecycle_transitions import auto_transition_work_item

    user = User(username="lifecycle-user-2", email="lifecycle2@example.test", password_hash="x")
    db.add(user)
    await db.flush()
    workflow = WorkItemWorkflowDefinition(
        name="Lifecycle dry run",
        states_json=[],
        mappings_json={"development": {"source_status": "In Progress", "sync_back": True}},
        sync_policy_json={"sync_mode": "dry_run_only"},
        is_default=True,
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    item = WorkItem(
        source_type="jira",
        source_instance="lifecycle-test",
        source_key="OCX-LC-2",
        title="Lifecycle test 2",
        source_status="Requested",
        work_state="intake",
        sync_state="imported",
    )
    await db.flush()
    db.add(workflow)
    db.add(item)
    await db.flush()
    result = await auto_transition_work_item(
        db, item=item, current_user=user, to_state="development", reason="agent started"
    )
    assert result and result["status"] == "applied"
    assert item.work_state == "development"
    # dry_run workflow: local state moved, Jira untouched
    assert result["preview"]["jira_sync_preview"]["will_mutate_jira"] is False


async def test_sync_upsert_does_not_regress_locally_transitioned_state(db):
    from app.models import User, WorkItem, WorkItemStateEvent
    from app.services.secure_work.jira.jira_item_upsert import upsert_jira_work_item

    user = User(username="sync-guard-user", email="sync-guard@example.test", password_hash="x")
    db.add(user)
    item = WorkItem(
        source_type="jira",
        source_instance="sync-guard-test",
        source_key="OCX-SYNC-1",
        title="Sync guard",
        source_status="In Progress",
        work_state="review",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    db.add(
        WorkItemStateEvent(
            work_item_id=item.id,
            to_state="review",
            from_state="development",
            actor_id=user.id,
            source="workflow_transition",
            dry_run=False,
        )
    )
    await db.flush()

    payload = {
        "source_type": "jira",
        "source_instance": "sync-guard-test",
        "source_key": "OCX-SYNC-1",
        "title": "Sync guard",
        "source_status": "In Progress",
        "work_state": "in_progress",
    }
    result = await upsert_jira_work_item(db, dict(payload), actor_id=user.id)
    assert item.work_state == "review"  # lifecycle NOT regressed
    assert result == ("unchanged", False)

    # without a local transition event the sync-derived state still updates
    plain = WorkItem(
        source_type="jira",
        source_instance="sync-guard-test",
        source_key="OCX-SYNC-2",
        title="Sync plain",
        source_status="Requested",
        work_state="intake",
        sync_state="imported",
    )
    db.add(plain)
    await db.flush()
    await upsert_jira_work_item(db, {**payload, "source_key": "OCX-SYNC-2"}, actor_id=user.id)
    assert plain.work_state == "in_progress"
