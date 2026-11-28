from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import AuditLog, Session
from app.services.audit_trail.timeline import export_audit_csv, list_audit
from app.services.audit_trail.workspace_scope import WORKSPACE_RESOURCE_TYPES, owner_known
from app.services.data_access import as_viewer
from app.services.execution_runtime.command_audit import CommandActor, record, run_actor
from app.services.project.private_workspace import ensure_private_workspace
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.observability_support import admin_user, call_as

APP = Path(__file__).resolve().parents[2] / "app"
# Kinds whose resource may be platform-wide: no reader hides them without a Workspace, but every write names it.
MAYBE_GLOBAL_TYPES = frozenset({"secure_work_cicd", "secure_work_cicd_finding", "secure_work_coding_execution",
                                "secure_work_coding_pipeline", "work_item", "work_item_sync_config",
                                "work_item_workflow"})


@pytest.fixture
async def private_events(db):
    owner = await user_named(db, f"audit-owner-{uuid.uuid4().hex[:6]}")
    admin = await admin_user(db)
    workspace = await ensure_private_workspace(db, owner)
    marker = uuid.uuid4().hex[:10]
    db.add(AuditLog(user_id=owner.id, action="code_repository.source_bound", resource_type="code_repository",
                    resource_id=f"{marker}-own", project_id=workspace.id, details={"connector_id": marker}))
    db.add(AuditLog(user_id=owner.id, action="code_repository.coding_setup_saved", resource_type="code_repository",
                    resource_id=f"{marker}-unresolved", details={}))
    db.add(AuditLog(user_id=admin.id, action="admin.connector.saved", resource_type="connector_config",
                    resource_id=f"{marker}-platform", details={}))
    await db.commit()
    return owner, admin, marker


def _objects(listed: dict) -> set[str]:
    return {item["object"].rsplit("-", 1)[-1] for item in listed["items"]}


async def test_the_owner_sees_the_event_of_their_private_repository(db, private_events):
    owner, _admin, marker = private_events
    with as_viewer(owner.id):
        listed = await list_audit(db, query=marker)
    assert _objects(listed) == {"own", "platform"} and listed["total"] == 2


async def test_a_foreign_platform_admin_neither_lists_counts_nor_exports_it(db, private_events):
    _owner, admin, marker = private_events
    with as_viewer(admin.id):
        listed = await list_audit(db, query=marker)
        exported = await export_audit_csv(db, viewer_id=admin.id, window_days=30, category=None, query=marker)
    assert _objects(listed) == {"platform"} and listed["total"] == 1
    assert f"{marker}-platform" in exported
    assert f"{marker}-own" not in exported and f"{marker}-unresolved" not in exported


async def test_an_event_of_a_workspace_resource_without_its_workspace_is_shown_to_nobody(db, private_events):
    owner, admin, marker = private_events
    for viewer in (owner, admin):
        with as_viewer(viewer.id):
            assert "unresolved" not in _objects(await list_audit(db, query=marker))


async def _visible(db, viewer_id: str, marker: str) -> set[str]:
    # The selection every audit reader applies (read filter plus ``owner_known``), without the admin categories.
    with as_viewer(viewer_id):
        return set((await db.execute(select(AuditLog.resource_id).where(
            owner_known(), AuditLog.resource_id.like(f"%{marker}%")))).scalars())


async def test_an_admin_sees_a_global_workflow_change_but_not_a_private_workspace_one(db):
    owner = await user_named(db, f"audit-flow-{uuid.uuid4().hex[:6]}")
    admin = await admin_user(db)
    workspace = await ensure_private_workspace(db, owner)
    marker = uuid.uuid4().hex[:10]
    for kind in ("work_item_workflow", "work_item_sync_config", "work_item"):
        db.add(AuditLog(user_id=admin.id, action="secure_work.workflow_updated", resource_type=kind,
                        resource_id=f"{marker}-{kind}", details={}))
    db.add(AuditLog(user_id=owner.id, action="secure_work.workflow_updated", resource_type="work_item_workflow",
                    resource_id=f"{marker}-private", project_id=workspace.id, details={}))
    await db.commit()
    assert await _visible(db, admin.id, marker) == {f"{marker}-work_item_workflow", f"{marker}-work_item_sync_config",
                                                    f"{marker}-work_item"}
    assert f"{marker}-private" in await _visible(db, owner.id, marker)


async def test_a_shared_workspace_connection_change_stays_visible_to_its_members(db):
    workspace = await seed_workspace(db)
    member = await seed_member(db, workspace_id=workspace, role="member")
    marker = uuid.uuid4().hex[:10]
    db.add(AuditLog(user_id=member, action="admin.workspace_connection.saved", resource_type="workspace_connection",
                    resource_id=f"{workspace}:{marker}", project_id=workspace, details={}))
    await db.commit()
    assert await _visible(db, member, marker) == {f"{workspace}:{marker}"}


async def _command_rows(db, viewer_id: str, resource_id: str) -> list[AuditLog]:
    with as_viewer(viewer_id):
        return list((await db.execute(select(AuditLog).where(AuditLog.resource_type == "server_command",
                                                             AuditLog.resource_id == resource_id))).scalars())


async def test_a_run_command_of_a_private_workspace_is_hidden_from_a_foreign_admin(db):
    owner = await user_named(db, f"audit-run-{uuid.uuid4().hex[:6]}")
    admin = await admin_user(db)
    workspace = await ensure_private_workspace(db, owner)
    run = SimpleNamespace(id=str(uuid.uuid4()), requested_by=owner.id, project_id=workspace.id)
    with run_actor(db, run, tool_name="workspace.prepare"):
        await record("git clone https://example.test/demo.git", verdict="executed", where="workspace.prepare")
    await db.commit()
    [row] = await _command_rows(db, owner.id, run.id)
    assert row.session_id is None and row.project_id == workspace.id
    assert await _command_rows(db, admin.id, run.id) == []


async def test_a_tool_call_command_carries_the_workspace_of_its_session(db):
    owner = await user_named(db, f"audit-tool-{uuid.uuid4().hex[:6]}")
    workspace = await ensure_private_workspace(db, owner)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=workspace.id, origin="chat")
    db.add(session)
    await db.flush()
    await record("ls", verdict="executed", where="bash",
                 actor=CommandActor(db=db, user_id=owner.id, session_id=session.id, tool_name="bash"))
    await db.commit()
    [row] = await _command_rows(db, owner.id, session.id)
    assert row.project_id == workspace.id


async def test_a_generic_request_row_of_a_workspace_route_carries_that_workspace(client, db):
    owner = await user_named(db, f"audit-route-{uuid.uuid4().hex[:6]}")
    workspace = await ensure_private_workspace(db, owner)
    await db.commit()
    response = await call_as(client, "PUT", f"/api/v1/workspaces/{workspace.id}/pr-review-bot/review-seat", owner,
                             json={"enabled": "yes"})
    assert response.status_code == 400
    row = (await db.execute(select(AuditLog).where(
        AuditLog.action == "PUT /api/v1/workspaces/{id}/pr-review-bot/review-seat",
        AuditLog.user_id == owner.id))).scalar_one()
    assert row.project_id == workspace.id


def _workspace_kind(call: ast.Call) -> str | None:
    kind = next((keyword.value for keyword in call.keywords if keyword.arg == "resource_type"), None)
    named = WORKSPACE_RESOURCE_TYPES | MAYBE_GLOBAL_TYPES
    if isinstance(kind, ast.Constant) and kind.value in named:
        return kind.value
    if isinstance(kind, ast.JoinedStr) and isinstance(kind.values[0], ast.Constant) and any(
            name.startswith(kind.values[0].value) for name in named):
        return ast.unparse(kind)
    return None


def test_every_audit_write_of_a_workspace_resource_names_its_workspace():
    missing = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "AuditLog"):
                continue
            kind = _workspace_kind(node)
            if kind and not any(keyword.arg == "project_id" for keyword in node.keywords):
                missing.append(f"{path.relative_to(APP.parent)}:{node.lineno} {kind}")
    assert missing == []
