from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Role, User, UserRole
from app.models.runtime.data_transfer import DataExportJob, DataImportJob
from app.models.runtime.prompt_template import PromptTemplate
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_support import answer_text, stable_headers

pytestmark = pytest.mark.asyncio

KEY = "run.read_contract"
CATALOG = "/api/v1/prompt-catalog"
ROUTING = "/api/v1/workflow-runs/triage-routing?project_id={id}"


async def _callers(db) -> tuple[User, User, dict[str, str]]:
    owner = await user_named(db, f"scope-owner-{uuid.uuid4().hex[:6]}")
    admin = await user_named(db, f"scope-admin-{uuid.uuid4().hex[:6]}")
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=admin.id, role_id=admin_role.id))
    private = await ensure_private_workspace(db, owner)
    workspaces = {"private": private.id, "shared": await seed_workspace(db), "unknown": str(uuid.uuid4())}
    await db.commit()
    return owner, admin, workspaces


def _assert_same_answer(answers, workspaces) -> None:
    private, unknown = answers["private"], answers["unknown"]
    masked = (workspaces["private"], workspaces["unknown"])
    assert private.status_code == unknown.status_code
    assert answer_text(private, *masked) == answer_text(unknown, *masked)
    assert stable_headers(private, *masked) == stable_headers(unknown, *masked)


async def _draft(client, user: User, workspace_id: str):
    return await client.post(f"{CATALOG}/keys/{KEY}/drafts", headers=bearer(user.id),
                             json={"scope_type": "workspace", "scope_id": workspace_id, "body": "Ours {run_id}."})


async def test_an_admin_writes_no_override_for_a_foreign_private_workspace_and_cannot_tell_it_exists(client, db):
    owner, admin, workspaces = await _callers(db)
    refused = {kind: await _draft(client, admin, workspaces[kind]) for kind in ("private", "unknown")}
    assert refused["private"].status_code == 403, refused["private"].text
    _assert_same_answer(refused, workspaces)
    assert (await _draft(client, admin, workspaces["shared"])).status_code == 201
    assert (await _draft(client, owner, workspaces["private"])).status_code == 201
    await db.rollback()
    scoped = (await db.execute(select(PromptTemplate.created_by).where(
        PromptTemplate.scope_id == workspaces["private"]))).scalars().all()
    assert scoped == [owner.id]


async def test_an_admin_sees_neither_the_scope_nor_the_override_of_a_foreign_private_workspace(client, db):
    owner, admin, workspaces = await _callers(db)
    assert (await _draft(client, owner, workspaces["private"])).status_code == 201
    detail = await client.get(f"{CATALOG}/keys/{KEY}", headers=bearer(admin.id))
    assert detail.status_code == 200, detail.text
    scope_ids = {item["scope_id"] for item in detail.json()["writable_scopes"]}
    assert workspaces["shared"] in scope_ids and workspaces["private"] not in scope_ids
    assert workspaces["private"] not in detail.text
    own = await client.get(f"{CATALOG}/keys/{KEY}", headers=bearer(owner.id))
    assert own.status_code == 200 and workspaces["private"] in own.text


async def test_an_admin_reads_and_writes_no_triage_routing_of_a_foreign_private_workspace(client, db):
    owner, admin, workspaces = await _callers(db)
    answers = {kind: await client.get(ROUTING.format(id=workspaces[kind]), headers=bearer(admin.id))
               for kind in ("private", "unknown")}
    assert answers["private"].status_code == 404
    _assert_same_answer(answers, workspaces)
    write = await client.put(ROUTING.format(id=workspaces["private"]), headers=bearer(admin.id), json={"routes": {}})
    assert write.status_code == 404
    shared = await client.get(ROUTING.format(id=workspaces["shared"]), headers=bearer(admin.id))
    assert shared.status_code == 200 and shared.json()["can_edit"] is True
    own = await client.get(ROUTING.format(id=workspaces["private"]), headers=bearer(owner.id))
    assert own.status_code == 200 and own.json()["can_edit"] is True


async def test_an_admin_lists_and_opens_no_data_transfer_job_of_a_foreign_private_workspace(client, db):
    owner, admin, workspaces = await _callers(db)
    jobs = {}
    for kind in ("private", "shared"):
        export = DataExportJob(created_by=owner.id, export_type="project", scope_type="project",
                               scope_id=workspaces[kind], status="completed")
        imported = DataImportJob(created_by=owner.id, import_type="project", target_project_id=workspaces[kind],
                                 status="completed")
        db.add_all([export, imported])
        await db.flush()
        jobs[kind] = (export.id, imported.id)
    await db.commit()
    exports = await client.get("/api/v1/data/exports?limit=100", headers=bearer(admin.id))
    imports = await client.get("/api/v1/data/imports?limit=100", headers=bearer(admin.id))
    listed = {item["id"] for item in exports.json()} | {item["id"] for item in imports.json()}
    assert set(jobs["shared"]) <= listed
    assert not set(jobs["private"]) & listed
    private_export, private_import = jobs["private"]
    assert (await client.get(f"/api/v1/data/exports/{private_export}", headers=bearer(admin.id))).status_code == 404
    assert (await client.get(f"/api/v1/data/imports/{private_import}", headers=bearer(admin.id))).status_code == 404
    own = await client.get(f"/api/v1/data/exports/{private_export}", headers=bearer(owner.id))
    assert own.status_code == 200
