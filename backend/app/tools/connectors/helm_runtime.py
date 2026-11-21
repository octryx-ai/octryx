"""Helm command runtime: workspace and policy resolution, command execution and the approval gate."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    build_command_change_preview,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .cloud_common import _run_subprocess
from .common import _normalize_string_list, _string


def _helm_workspace_root(context: ToolContext) -> Path:
    root = Path(context.workspace_root or Path.cwd()).resolve()
    configured = _string(context.project_config.get("helm_workspace_root"))
    if not configured:
        return root
    candidate = Path(configured)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"helm_workspace_root must stay inside workspace root: {root}")
    return resolved


def _helm_binary(context: ToolContext) -> str:
    return _string(context.project_config.get("helm_binary") or "helm")


def _helm_namespace(context: ToolContext, params: dict[str, Any]) -> str:
    namespace = _string(params.get("namespace") or context.project_config.get("helm_namespace"))
    allowed = _normalize_string_list(context.project_config.get("helm_allowed_namespaces"))
    if not namespace and len(allowed) == 1:
        namespace = allowed[0]
    if not namespace:
        return ""
    if allowed and namespace not in allowed:
        raise ValueError("namespace is not allowed")
    return namespace


def _helm_release_name(context: ToolContext, params: dict[str, Any]) -> str:
    release_name = _string(params.get("release_name") or params.get("name"))
    allowed = _normalize_string_list(context.project_config.get("helm_allowed_releases"))
    if not release_name and len(allowed) == 1:
        release_name = allowed[0]
    if not release_name:
        raise ValueError("release_name is required")
    if allowed and release_name not in allowed:
        raise ValueError("release_name is not allowed")
    return release_name


def _helm_chart_ref(context: ToolContext, params: dict[str, Any]) -> str:
    chart = _string(params.get("chart") or context.project_config.get("helm_chart"))
    if not chart:
        raise ValueError("chart is required")
    allowed = _normalize_string_list(context.project_config.get("helm_allowed_charts"))
    if allowed:
        workspace_root = _helm_workspace_root(context)
        candidate = Path(chart)
        resolved = (workspace_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if chart not in allowed and str(resolved) not in allowed:
            raise ValueError("chart is not allowed")
    candidate = Path(chart)
    if candidate.exists() or "/" in chart or chart.startswith("."):
        workspace_root = _helm_workspace_root(context)
        resolved = (workspace_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if workspace_root not in resolved.parents and resolved != workspace_root:
            raise ValueError(f"chart must stay inside workspace root: {workspace_root}")
        return str(resolved)
    return chart


def _helm_env(context: ToolContext) -> dict[str, str]:
    env = dict(os.environ)
    kubeconfig = _string(context.project_config.get("helm_kubeconfig"))
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    return env


async def _helm_json(context: ToolContext, args: list[str]) -> Any:
    binary = _helm_binary(context)
    if shutil.which(binary) is None and not Path(binary).exists():
        raise ValueError(f"{binary} is not available on PATH.")
    code, stdout, _ = await _run_subprocess(
        [binary, *args], env=_helm_env(context), cwd=str(_helm_workspace_root(context))
    )
    if code != 0:
        # A read (list/status/history) failure is reported as facts; helm output can carry hosts and values.
        raise ValueError(f"helm_command_failed exit_code={code}")
    return json.loads(stdout or "{}")


async def _helm_text(context: ToolContext, args: list[str]) -> dict[str, Any]:
    binary = _helm_binary(context)
    if shutil.which(binary) is None and not Path(binary).exists():
        return {"error": f"{binary} is not available on PATH."}
    code, stdout, stderr = await _run_subprocess(
        [binary, *args], env=_helm_env(context), cwd=str(_helm_workspace_root(context))
    )
    # ``--set`` values can hold secrets; the shown command goes through the redactor.
    shown_command = redact_process_output(" ".join([binary, *args]))
    if code != 0:
        # The agent ran this upgrade/rollback and must see why it failed (template or value error):
        # stderr is kept through the redactor, stdout is not repeated.
        return {
            "error": f"helm_command_failed exit_code={code}",
            "error_code": "helm_command_failed",
            "exit_code": code,
            "stderr": redact_process_output(stderr),
            "command": shown_command,
        }
    # The helm output (release notes, dry-run manifests) is the product result; redacted.
    return {
        "status": "completed",
        "exit_code": code,
        "stdout": redact_process_output(stdout),
        "stderr": redact_process_output(stderr),
        "command": shown_command,
    }


async def _maybe_block_helm_action_with_approval(
    tool_name: str, params: dict[str, Any], context: ToolContext, *, command: list[str]
) -> dict[str, Any] | None:
    if await consume_change_preview_grant(
        context.db, session_id=context.session_id, tool_name=tool_name, payload=params, context=context
    ):
        return None
    if context.db is None or not context.user_id:
        return None
    preview_payload = build_command_change_preview(tool_name, command, cwd=str(_helm_workspace_root(context)))
    preview_payload["kind"] = "helm"
    preview_payload["title"] = "Helm release change"
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve Helm change for {tool_name}",
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
        "error": "Execution blocked pending Helm approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }
