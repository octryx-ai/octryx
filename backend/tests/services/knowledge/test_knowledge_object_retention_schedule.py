from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import select

from app.models import Role, User, UserRole
from app.models.project.knowledge_object_retention import (
    FINDING_STATE_SUPERSEDED,
    RETENTION_FAILURE_CONTRACT,
    RETENTION_FAILURE_NOT_CONFIGURED,
    RETENTION_FAILURE_UNAVAILABLE,
    RUN_STATE_COMPLETED,
    RUN_STATE_FAILED,
    RUN_STATE_LEGAL_HOLD,
    KnowledgeObjectReconciliationFinding,
)
from app.services.data_access import PlatformMaintenance, current_viewer
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.retention import scheduled
from app.services.knowledge.retention.holds import acquire_hold
from app.services.knowledge.retention.reconcile import reconcile_workspace
from app.services.knowledge.retention.reports import latest_run_report
from app.services.knowledge.retention.scheduled import (
    ENV_RECONCILE_AWS_PROFILE,
    RECONCILE_REASON,
    REQUESTED_BY,
    KnowledgeRetentionReconcileWorker,
    maintenance_from_environment,
)
from app.services.project.private_workspace import ensure_private_workspace
from tests.knowledge_evidence_seed_support import fetch_user, seed_workspace
from tests.services.knowledge.knowledge_object_retention_support import (
    OPERATOR,
    _abandon,
    _authorized,
    _set_policy,
    _wired,
)
from tests.support.knowledge_evidence_s3_support import BUCKET, PREFIX


@pytest.fixture
def as_user(db):
    from app.main import app
    from app.services.auth import get_current_user

    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


def _shared(db):
    @contextlib.asynccontextmanager
    async def factory():
        yield db

    return factory


def _worker(db, maintain) -> KnowledgeRetentionReconcileWorker:
    return KnowledgeRetentionReconcileWorker(_shared(db), maintenance_factory=lambda: maintain)


def _latest(workspace_id: str) -> str:
    return f"/api/v1/admin/knowledge/retention/workspaces/{workspace_id}/runs/latest"


async def _put(runtime, client, authorized, data: bytes, *, age_hours: int) -> str:
    stored = await runtime.object_store.put_if_absent(authorized.workspace, data)
    client.age(stored.ref.key, hours=age_hours)
    return stored.ref.key


async def _global_admin(db, owner: User) -> None:
    role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=owner.id, role_id=role.id))
    await db.flush()


async def test_the_scheduled_pass_reconciles_each_workspace_with_a_policy_and_the_latest_run_shows_it(
    client, db, as_user, auth_user
):
    governed = await seed_workspace(db)
    ungoverned = await seed_workspace(db)
    authorized = await _authorized(db, governed)
    runtime, maintain, object_client = _wired()
    key = await _abandon(runtime, object_client, authorized, age_hours=200)
    await _set_policy(db, governed)

    outcome = await _worker(db, maintain).run_once()

    assert outcome["reconciled"] >= 1 and outcome["failed"] == 0
    as_user(auth_user)
    body = (await client.get(_latest(governed))).json()
    assert body["reconciled"] is True and body["state"] == RUN_STATE_COMPLETED
    assert body["requested_by"] == REQUESTED_BY
    assert body["counts"]["unreferenced_objects"] == 1 and body["counts"]["deletion_candidates"] == 1
    assert len(body["findings"]) == 1 and body["findings"][0]["age_eligible"] is True
    assert (await client.get(_latest(ungoverned))).json() == {"workspace_id": ungoverned, "reconciled": False}
    assert (maintain.bucket, key) in object_client.source.objects


async def test_the_pass_reads_under_its_pinned_platform_maintenance(db, monkeypatch):
    workspace_id = await seed_workspace(db)
    await _set_policy(db, workspace_id)
    _runtime, maintain, _client = _wired()
    seen = []

    async def recording(*_args, **_kwargs):
        seen.append(current_viewer())

    monkeypatch.setattr(scheduled, "reconcile_workspace", recording)
    await _worker(db, maintain).run_once()

    assert seen and all(isinstance(viewer, PlatformMaintenance) for viewer in seen)
    assert {viewer.reason for viewer in seen} == {RECONCILE_REASON}


async def test_a_live_hold_keeps_its_object_out_of_the_findings(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, object_client = _wired()
    held_key = await _put(runtime, object_client, authorized, b"held object\n", age_hours=200)
    await _put(runtime, object_client, authorized, b"free object\n", age_hours=200)
    await _set_policy(db, workspace_id)
    first = await reconcile_workspace(db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR)
    held_finding = (
        await db.execute(
            select(KnowledgeObjectReconciliationFinding.id).where(
                KnowledgeObjectReconciliationFinding.run_id == first.run_id,
                KnowledgeObjectReconciliationFinding.object_key == held_key,
            )
        )
    ).scalar_one()
    assert await acquire_hold(
        db, project_id=workspace_id, object_key=held_key, finding_id=held_finding, acquired_by=OPERATOR
    )

    await _worker(db, maintain).run_once()

    findings = (
        await db.execute(
            select(KnowledgeObjectReconciliationFinding.object_key).where(
                KnowledgeObjectReconciliationFinding.project_id == workspace_id,
                KnowledgeObjectReconciliationFinding.run_id != first.run_id,
            )
        )
    ).scalars().all()
    assert len(findings) == 1 and held_key not in findings


async def test_a_legal_hold_inventories_reports_and_flags_nothing(client, db, as_user, auth_user):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, object_client = _wired()
    key = await _abandon(runtime, object_client, authorized, age_hours=200)
    await _set_policy(db, workspace_id)
    earlier = await reconcile_workspace(db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR)
    as_user(auth_user)
    held = await client.put(
        _latest(workspace_id).replace("/runs/latest", "/policy"),
        json={"mode": "report_only", "min_object_age_hours": 24, "legal_hold": True},
    )
    assert held.status_code == 200 and held.json()["legal_hold"] is True
    listed = len(object_client.calls)

    await _worker(db, maintain).run_once()

    body = (await client.get(_latest(workspace_id))).json()
    assert body["state"] == RUN_STATE_LEGAL_HOLD and body["findings"] == []
    assert set(body["counts"].values()) == {0}
    assert len(object_client.calls) == listed
    stale = await db.get(KnowledgeObjectReconciliationFinding, earlier.findings[0].finding_id)
    assert stale.state == FINDING_STATE_SUPERSEDED
    assert (maintain.bucket, key) in object_client.source.objects


async def test_an_inventory_failure_is_visible_on_the_run(client, db, as_user, auth_user):
    workspace_id = await seed_workspace(db)
    await _set_policy(db, workspace_id)
    _runtime, maintain, object_client = _wired()
    object_client.unavailable = True

    outcome = await _worker(db, maintain).run_once()

    assert outcome["failed"] >= 1
    as_user(auth_user)
    body = (await client.get(_latest(workspace_id))).json()
    assert (body["state"], body["failure"]) == (RUN_STATE_FAILED, RETENTION_FAILURE_UNAVAILABLE)


async def test_an_unconfigured_object_store_is_visible_on_the_run(db):
    workspace_id = await seed_workspace(db)
    await _set_policy(db, workspace_id)
    worker = KnowledgeRetentionReconcileWorker(_shared(db), maintenance_factory=lambda: maintenance_from_environment({}))

    await worker.run_once()

    report = await latest_run_report(db, workspace_id)
    assert (report.state, report.failure) == (RUN_STATE_FAILED, RETENTION_FAILURE_NOT_CONFIGURED)


async def test_a_crash_inside_one_workspace_is_recorded_and_the_others_still_run(db, monkeypatch):
    crashing, healthy = sorted([await seed_workspace(db), await seed_workspace(db)])
    for workspace_id in (crashing, healthy):
        await _set_policy(db, workspace_id)
    _runtime, maintain, _client = _wired()
    real = scheduled.reconcile_workspace

    async def flaky(db_, *, project_id, **kwargs):
        if project_id == crashing:
            raise RuntimeError("synthetic crash")
        return await real(db_, project_id=project_id, **kwargs)

    monkeypatch.setattr(scheduled, "reconcile_workspace", flaky)
    await _worker(db, maintain).run_once()

    crashed = await latest_run_report(db, crashing)
    assert (crashed.state, crashed.failure) == (RUN_STATE_FAILED, RETENTION_FAILURE_CONTRACT)
    assert (await latest_run_report(db, healthy)).state == RUN_STATE_COMPLETED


async def test_a_private_workspace_run_is_visible_to_its_owner_and_not_to_another_admin(
    client, db, as_user, auth_user
):
    owner = User(username=f"owner{uuid.uuid4().hex[:8]}", email=f"owner{uuid.uuid4().hex[:8]}@example.com",
                 password_hash="x", is_active=True)
    db.add(owner)
    await db.flush()
    await _global_admin(db, owner)
    workspace = await ensure_private_workspace(db, owner)
    await db.commit()
    authorized = await authorize_workspace(
        db, current_user=await fetch_user(db, owner.id), workspace_id=workspace.id, require_author=True
    )
    runtime, maintain, object_client = _wired()
    await _abandon(runtime, object_client, authorized, age_hours=200)
    await _set_policy(db, workspace.id)

    await _worker(db, maintain).run_once()

    as_user(await fetch_user(db, owner.id))
    mine = await client.get(_latest(workspace.id))
    assert mine.status_code == 200 and mine.json()["reconciled"] is True
    assert mine.json()["counts"]["unreferenced_objects"] == 1
    as_user(auth_user)
    assert (await client.get(_latest(workspace.id))).status_code == 404


def test_the_reconciliation_identity_profile_replaces_the_application_profile():
    environ = {
        "OCTRYX_KNOWLEDGE_OBJECT_ENDPOINT_URL": "http://127.0.0.1:9000",
        "OCTRYX_KNOWLEDGE_OBJECT_BUCKET": BUCKET,
        "OCTRYX_KNOWLEDGE_OBJECT_REGION": "us-east-1",
        "OCTRYX_KNOWLEDGE_OBJECT_PREFIX": PREFIX,
        "OCTRYX_KNOWLEDGE_OBJECT_AWS_PROFILE": "application",
    }

    assert maintenance_from_environment(environ)._config.credentials_profile == "application"
    reconciling = maintenance_from_environment({**environ, ENV_RECONCILE_AWS_PROFILE: "reconciliation"})
    assert reconciling._config.credentials_profile == "reconciliation"
