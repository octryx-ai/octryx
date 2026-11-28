"""Terraform connector tools (plan, apply, state, output, workspace) and their native connection test."""

# ruff: noqa: F401,I001,E501

import asyncio
import json
import uuid
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import Approval, ChangePreview, Session, User
from app.services.change_preview import build_change_request_fingerprint
from app.services.connector_test_service import run_connector_connection_test
from app.tools.registry import execute_tool
from app.tools.context import ToolContext


def _write_fake_terraform_binary(tmp_path: Path) -> Path:
    script = tmp_path / "fake-terraform.py"
    script.write_text(
        """#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path.cwd()
args = sys.argv[1:]
workspace_file = root / '.workspace'
current_workspace = workspace_file.read_text().strip() if workspace_file.exists() else 'default'

def emit(payload='', code=0, stream='stdout'):
    target = sys.stdout if stream == 'stdout' else sys.stderr
    if isinstance(payload, (dict, list)):
        target.write(json.dumps(payload))
    else:
        target.write(str(payload))
    if payload and not str(payload).endswith('\\n'):
        target.write('\\n')
    raise SystemExit(code)

if args == ['version', '-json']:
    emit({'terraform_version': '1.9.9'})
if len(args) >= 3 and args[0] == 'workspace' and args[1] == 'select':
    if args[2] in {'default', 'prod'}:
        workspace_file.write_text(args[2])
        emit(f'Switched to workspace {args[2]}')
    emit(f'Workspace {args[2]} not found', code=1, stream='stderr')
if len(args) >= 3 and args[0] == 'workspace' and args[1] == 'new':
    workspace_file.write_text(args[2])
    emit(f'Created and switched to workspace {args[2]}')
if args[:4] == ['plan', '-no-color', '-input=false', '-detailed-exitcode']:
    plan_path = pathlib.Path(args[args.index('-out') + 1])
    plan_path.write_text('fake plan')
    emit('Plan: 1 to add, 0 to change, 0 to destroy', code=2)
if args[:3] == ['apply', '-no-color', '-input=false']:
    emit('Apply complete! Resources: 1 added, 0 changed, 0 destroyed.')
if args == ['show', '-json']:
    emit({'format_version': '1.0', 'values': {'root_module': {'resources': [{'address': 'aws_s3_bucket.demo'}]}}})
if args == ['state', 'list']:
    emit('aws_s3_bucket.demo\\naws_iam_role.demo')
if args[:2] == ['output', '-json']:
    if len(args) == 3 and args[2] == 'bucket_name':
        emit({'sensitive': False, 'type': 'string', 'value': 'acme-orders-bucket'})
    emit({'bucket_name': {'sensitive': False, 'type': 'string', 'value': 'acme-orders-bucket'}})
emit(f'unhandled args: {args}', code=1, stream='stderr')
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_terraform_tools_cover_plan_apply_state_output_and_workspace(db, tmp_path, auth_user):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=auth_user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        metadata_={},
    )
    db.add(session)
    await db.commit()

    binary = _write_fake_terraform_binary(tmp_path)
    context = ToolContext(
        user_id=auth_user.id,
        project_ids=[],
        roles=["admin"],
        session_id=session.id,
        project_config={
            "tool_policy": {"high_risk_grants": ["apply", "workspace_select"]},
            "terraform_root": ".",
            "terraform_binary": str(binary),
            "terraform_allowed_workspaces": ["default", "prod"],
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root=str(tmp_path),
        db=db,
    )

    workspace = await execute_tool("workspace_select", {"workspace": "prod", "create_if_missing": True}, context)
    assert workspace["workspace"] == "prod"

    plan = await execute_tool("plan", {"workspace": "prod"}, context)
    assert plan["has_changes"] is True
    assert Path(plan["plan_file"]).exists()

    show_state = await execute_tool("show_state", {"workspace": "prod"}, context)
    assert show_state["format"] == "json"
    assert show_state["state"]["values"]["root_module"]["resources"][0]["address"] == "aws_s3_bucket.demo"

    resources = await execute_tool("list_resources", {"workspace": "prod"}, context)
    assert resources["count"] == 2
    assert "aws_s3_bucket.demo" in resources["resources"]

    output_all = await execute_tool("get_output", {"workspace": "prod"}, context)
    assert output_all["output"]["bucket_name"]["value"] == "acme-orders-bucket"

    output_one = await execute_tool("get_output", {"workspace": "prod", "name": "bucket_name"}, context)
    assert output_one["output"]["value"] == "acme-orders-bucket"

    apply_blocked = await execute_tool("apply", {"workspace": "prod", "plan_file": plan["plan_file"]}, context)
    assert apply_blocked["approval_required"] is True
    assert apply_blocked["change_preview"]["kind"] == "terraform"
    approval = (await db.execute(select(Approval).where(Approval.id == apply_blocked["approval_id"]))).scalar_one()
    assert approval.status == "pending"
    preview = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == approval.id))).scalar_one()
    assert "apply" in preview.preview_json

    session.metadata_ = {
        "approval_grants": [
            {
                "approval_id": approval.id,
                "tool_name": "apply",
                "request_fingerprint": build_change_request_fingerprint(
                    "apply", {"workspace": "prod", "plan_file": plan["plan_file"]}
                ),
            }
        ]
    }
    await db.commit()
    applied = await execute_tool("apply", {"workspace": "prod", "plan_file": plan["plan_file"]}, context)
    assert applied["summary"] == "Terraform apply completed successfully."


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_terraform_connector_health_supports_native_connection_test(tmp_path):
    binary = _write_fake_terraform_binary(tmp_path)
    result = await run_connector_connection_test(
        "terraform",
        {
            "terraform_root": ".",
            "terraform_binary": str(binary),
        },
    )
    assert result["ok"] is True
    assert result["summary"] == "Terraform probe succeeded."
    assert result["version"] == "1.9.9"
