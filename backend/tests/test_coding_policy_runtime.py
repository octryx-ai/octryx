import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, User
from app.services.coding_policy_runtime import enforce_workspace_path_policy
from app.tools.code_impl._code_edit import EditFileTool
from app.tools.code_impl._code_patch import ApplyPatchTool
from app.tools.context import ToolContext


async def _deny_path(db, *, project: Project, glob: str) -> None:
    """A Workspace tool rule that denies edits under ``glob``."""
    project.config = {**(project.config or {}), "agent_gateway_policy": {"tool_rules": [
        {"id": "no-runtime", "kind": "path_denied", "tools": ["Edit", "Write"], "glob": glob}]}}
    await db.flush()


@pytest.mark.asyncio
async def test_runtime_policy_decisions_allow_and_block_and_are_audited(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _deny_path(db, project=project, glob="backend/app/runtime/*")

    common = {
        "user_id": user.id,
        "session_id": None,
        "project_id": project.id,
        "work_item_id": None,
        "tool_name": "edit_workspace_file",
    }
    allowed = await enforce_workspace_path_policy(db, paths=["backend/app/main.py"], **common)
    blocked = await enforce_workspace_path_policy(db, paths=["backend/app/runtime/execution.py"], **common)

    assert allowed["status"] == "allowed"
    assert blocked["status"] == "blocked"
    assert blocked["blocking"] is True
    assert blocked["outcomes"][0]["policy_type"] == "workspace_tool_rule"
    assert blocked["outcomes"][0]["evidence"]["paths"] == ["backend/app/runtime/execution.py"]

    audits = (
        await db.execute(select(AuditLog).where(AuditLog.action == "secure_work.coding_policy_runtime_decision"))
    ).scalars().all()
    assert {entry.details["decision"]["status"] for entry in audits} == {"allowed", "blocked"}


@pytest.mark.asyncio
async def test_edit_workspace_file_blocks_protected_path_policy(db, tmp_path):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _deny_path(db, project=project, glob="backend/app/runtime/*")
    target = tmp_path / "backend" / "app" / "runtime" / "execution.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    context = ToolContext(
        user_id=user.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="policy-session",
        project_config={"project_id": project.id},
        workspace_root=str(tmp_path),
        db=db,
    )

    result = await EditFileTool().execute(
        {"path": "backend/app/runtime/execution.py", "old_string": "value = 1", "new_string": "value = 2"},
        context,
    )

    assert result["coding_policy_decision"]["status"] == "blocked"
    assert "blocked this workspace mutation" in result["error"]
    assert target.read_text(encoding="utf-8") == "value = 1\n"
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "secure_work.coding_policy_runtime_decision"))
    ).scalar_one()
    assert audit.details["decision"]["status"] == "blocked"
    assert audit.details["paths"] == ["backend/app/runtime/execution.py"]


@pytest.mark.asyncio
async def test_apply_patch_workspace_blocks_protected_path_policy(db, tmp_path):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await _deny_path(db, project=project, glob="backend/app/runtime/*")
    target = tmp_path / "backend" / "app" / "runtime" / "execution.py"
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    context = ToolContext(
        user_id=user.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="policy-session",
        project_config={"project_id": project.id},
        workspace_root=str(tmp_path),
        db=db,
    )
    patch = """--- a/backend/app/runtime/execution.py
+++ b/backend/app/runtime/execution.py
@@ -1 +1 @@
-old
+new
"""

    result = await ApplyPatchTool().execute({"patch": patch}, context)

    assert result["coding_policy_decision"]["status"] == "blocked"
    assert result["execution_event"]["status"] == "failed"
    assert target.read_text(encoding="utf-8") == "old\n"
