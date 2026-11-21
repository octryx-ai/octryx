"""Runtime helpers for Ansible connector tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    build_command_change_preview,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ..context import ToolContext
from .common import _normalize_string_list, _string


def _ansible_workspace_root(context: ToolContext) -> Path:
    return Path(context.workspace_root or Path.cwd()).resolve()


def _ansible_playbook_root(context: ToolContext) -> Path:
    root = _ansible_workspace_root(context)
    configured = _string(context.project_config.get("ansible_playbook_root"))
    if not configured:
        return root
    candidate = Path(configured)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"ansible_playbook_root must stay inside workspace root: {root}")
    return resolved


def _ansible_binary(context: ToolContext, field: str, default: str) -> str:
    explicit = _string(context.project_config.get(field))
    return explicit or default


def _ansible_inventory_path(context: ToolContext) -> Path:
    root = _ansible_workspace_root(context)
    configured = _string(context.project_config.get("ansible_inventory_path"))
    if not configured:
        raise ValueError("ansible_inventory_path is required")
    candidate = Path(configured)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"ansible_inventory_path must stay inside workspace root: {root}")
    return resolved


def _resolve_ansible_playbook(context: ToolContext, params: dict[str, Any]) -> Path:
    playbook_root = _ansible_playbook_root(context)
    playbook_value = _string(params.get("playbook"))
    allowed = [
        item.strip()
        for item in _normalize_string_list(context.project_config.get("ansible_allowed_playbooks"))
        if item.strip()
    ]
    if not playbook_value and len(allowed) == 1:
        playbook_value = allowed[0]
    if not playbook_value:
        raise ValueError("playbook is required")
    candidate = Path(playbook_value)
    resolved = (playbook_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    workspace_root = _ansible_workspace_root(context)
    if workspace_root not in resolved.parents and resolved != workspace_root:
        raise ValueError(f"playbook must stay inside workspace root: {workspace_root}")
    if playbook_root not in resolved.parents and resolved != playbook_root:
        raise ValueError(f"playbook must stay inside ansible_playbook_root: {playbook_root}")
    relative = resolved.relative_to(playbook_root).as_posix()
    if allowed and relative not in allowed:
        raise ValueError(f"playbook '{relative}' is not allowed")
    return resolved


def _resolve_ansible_host_pattern(context: ToolContext, params: dict[str, Any], *, default: str = "all") -> str:
    pattern = _string(params.get("host_pattern") or params.get("limit") or default)
    allowed = [
        item.strip()
        for item in _normalize_string_list(context.project_config.get("ansible_allowed_hosts"))
        if item.strip()
    ]
    if not pattern and len(allowed) == 1:
        pattern = allowed[0]
    if allowed and pattern not in allowed:
        raise ValueError(f"host_pattern '{pattern}' is not allowed")
    return pattern


def _ansible_extra_vars(params: dict[str, Any]) -> str | None:
    extra_vars = params.get("extra_vars")
    if isinstance(extra_vars, dict):
        return json.dumps(extra_vars)
    if isinstance(extra_vars, str) and extra_vars.strip():
        return extra_vars.strip()
    return None


def _ansible_tags(params: dict[str, Any]) -> str | None:
    tags = _normalize_string_list(params.get("tags"))
    return ",".join(tags) if tags else None


async def _maybe_block_ansible_playbook_with_approval(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    command: list[str],
    cwd: str,
) -> dict[str, Any] | None:
    if await consume_change_preview_grant(
        context.db, session_id=context.session_id, tool_name=tool_name, payload=params, context=context
    ):
        return None
    if context.db is None or not context.user_id:
        return None
    preview_payload = build_command_change_preview(tool_name, command, cwd=cwd)
    preview_payload["kind"] = "ansible"
    preview_payload["title"] = "Ansible playbook run"
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve Ansible change for {tool_name}",
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
        "error": "Execution blocked pending Ansible approval.",
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "change_preview": preview_payload,
        "tool_name": tool_name,
    }
