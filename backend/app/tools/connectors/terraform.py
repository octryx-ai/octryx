"""Terraform connector tools."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    build_command_change_preview,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ..context import ToolContext
from .common import _string
from .terraform_core import (
    _terraform_allowed_workspaces,
    _terraform_binary,
    _terraform_run,
    _terraform_var_file,
    _terraform_workspace_root,
)


async def _maybe_block_terraform_apply_with_approval(
    tool_name: str,
    params: dict[str, object],
    context: ToolContext,
    *,
    command: list[str],
    cwd: str,
) -> dict[str, object] | None:
    if await consume_change_preview_grant(
        context.db, session_id=context.session_id, tool_name=tool_name, payload=params, context=context
    ):
        return None
    if context.db is None or not context.user_id:
        return None
    preview_payload = build_command_change_preview(tool_name, command, cwd=cwd)
    preview_payload["kind"] = "terraform"
    preview_payload["title"] = "Terraform apply"
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve Terraform change for {tool_name}",
        reason=f"Command: {' '.join(command)}",
    )
    preview = await upsert_change_preview(
        context.db,
        tool_name=tool_name,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(tool_name, params),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending Terraform approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }


class TerraformPlanTool:
    name = "plan"
    description = "Run terraform or opentofu plan and persist a reusable plan file."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        cwd = _terraform_workspace_root(context)
        plan_dir = cwd / ".octryx" / "terraform-plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = _string(params.get("plan_file"))
        plan_path = (
            (cwd / plan_file).resolve()
            if plan_file and not Path(plan_file).is_absolute()
            else (Path(plan_file).resolve() if plan_file else plan_dir / f"{uuid.uuid4().hex}.tfplan")
        )
        if cwd not in plan_path.parents and plan_path != cwd:
            return {"error": "plan_file must stay inside terraform_root"}
        args = ["plan", "-no-color", "-input=false", "-detailed-exitcode", "-out", str(plan_path)]
        var_file = _terraform_var_file(context, params)
        if var_file:
            args.extend(["-var-file", var_file])
        if bool(params.get("destroy")):
            args.append("-destroy")
        result = await _terraform_run(
            context, args, params=params, timeout=int(params.get("timeout_sec") or 180), allow_exit_codes=(0, 2)
        )
        if result.get("error"):
            return result
        has_changes = int(result.get("exit_code") or 0) == 2
        return {
            "cwd": result["cwd"],
            "workspace": result.get("workspace") or "",
            "plan_file": str(plan_path),
            "has_changes": has_changes,
            "stdout": result.get("stdout") or "",
            "stderr": result.get("stderr") or "",
            "summary": "Terraform plan detected changes." if has_changes else "Terraform plan found no changes.",
            "binary": result.get("binary"),
        }


class TerraformApplyTool:
    name = "apply"
    description = "Run terraform or opentofu apply with an approval gate."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        cwd = _terraform_workspace_root(context)
        args = ["apply", "-no-color", "-input=false", "-auto-approve"]
        plan_file = _string(params.get("plan_file"))
        if plan_file:
            args.append(plan_file)
        var_file = _terraform_var_file(context, params)
        if var_file and not plan_file:
            args.extend(["-var-file", var_file])
        blocked = await _maybe_block_terraform_apply_with_approval(
            self.name, params, context, command=[_terraform_binary(context), *args], cwd=str(cwd)
        )
        if blocked is not None:
            return blocked
        result = await _terraform_run(context, args, params=params, timeout=int(params.get("timeout_sec") or 300))
        if result.get("error"):
            return result
        return {
            "cwd": result["cwd"],
            "workspace": result.get("workspace") or "",
            "stdout": result.get("stdout") or "",
            "stderr": result.get("stderr") or "",
            "summary": "Terraform apply completed successfully.",
            "binary": result.get("binary"),
        }


class TerraformShowStateTool:
    name = "show_state"
    description = "Show current terraform or opentofu state in JSON form when available."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        result = await _terraform_run(
            context, ["show", "-json"], params=params, timeout=int(params.get("timeout_sec") or 120)
        )
        if result.get("error"):
            fallback = await _terraform_run(
                context, ["show", "-no-color"], params=params, timeout=int(params.get("timeout_sec") or 120)
            )
            if fallback.get("error"):
                return fallback
            return {
                "cwd": fallback["cwd"],
                "workspace": fallback.get("workspace") or "",
                "format": "text",
                "state": fallback.get("stdout") or "",
                "binary": fallback.get("binary"),
            }
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            payload = {"raw": result.get("stdout") or ""}
        return {
            "cwd": result["cwd"],
            "workspace": result.get("workspace") or "",
            "format": "json",
            "state": payload,
            "binary": result.get("binary"),
        }


class TerraformListResourcesTool:
    name = "list_resources"
    description = "List resources from terraform or opentofu state."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        result = await _terraform_run(
            context, ["state", "list"], params=params, timeout=int(params.get("timeout_sec") or 120)
        )
        if result.get("error"):
            return result
        resources = [line.strip() for line in (result.get("stdout") or "").splitlines() if line.strip()]
        return {
            "cwd": result["cwd"],
            "workspace": result.get("workspace") or "",
            "count": len(resources),
            "resources": resources,
            "binary": result.get("binary"),
        }


class TerraformGetOutputTool:
    name = "get_output"
    description = "Read terraform or opentofu outputs in JSON form."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        output_name = _string(params.get("name"))
        args = ["output", "-json"]
        if output_name:
            args.append(output_name)
        result = await _terraform_run(context, args, params=params, timeout=int(params.get("timeout_sec") or 120))
        if result.get("error"):
            return result
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            payload = result.get("stdout") or ""
        return {
            "cwd": result["cwd"],
            "workspace": result.get("workspace") or "",
            "name": output_name or "",
            "output": payload,
            "binary": result.get("binary"),
        }


class TerraformWorkspaceSelectTool:
    name = "workspace_select"
    description = "Select a terraform or opentofu workspace, optionally creating it if missing."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        workspace = _string(params.get("workspace"))
        if not workspace:
            return {"error": "workspace is required"}
        allowed = _terraform_allowed_workspaces(context)
        if allowed and workspace not in allowed:
            return {"error": f"workspace '{workspace}' is not allowed"}
        result = await _terraform_run(
            context,
            ["workspace", "select", workspace],
            params={"workspace": ""},
            timeout=int(params.get("timeout_sec") or 60),
        )
        if result.get("error") and bool(params.get("create_if_missing")):
            result = await _terraform_run(
                context,
                ["workspace", "new", workspace],
                params={"workspace": ""},
                timeout=int(params.get("timeout_sec") or 60),
            )
        elif result.get("error"):
            return result
        return {
            "cwd": result["cwd"],
            "workspace": workspace,
            "summary": f"Selected workspace {workspace}.",
            "stdout": result.get("stdout") or "",
            "stderr": result.get("stderr") or "",
            "binary": result.get("binary"),
        }
