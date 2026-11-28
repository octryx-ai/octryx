"""Assignment-policy helpers for workspace execution views."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException

from .execution_view import normalize_workspace_execution_view

AssignmentMode = Literal["all_installed", "selected_only"]


def _normalize_mode(value: Any) -> AssignmentMode:
    return "selected_only" if str(value or "").strip() == "selected_only" else "all_installed"


def _bindings_for_kind(workspace_execution_view: dict[str, Any] | None, kind: str) -> list[dict[str, Any]]:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return []
    return list((normalized_view.get("bindings_by_kind") or {}).get(kind) or [])


def agent_assignment_mode(workspace_execution_view: dict[str, Any] | None) -> AssignmentMode:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return "all_installed"
    routing_policy = normalized_view.get("routing_policy") or {}
    return _normalize_mode(routing_policy.get("agent_assignment_mode"))


def runtime_assignment_mode(workspace_execution_view: dict[str, Any] | None) -> AssignmentMode:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return "all_installed"
    runtime_policy = normalized_view.get("runtime_policy") or {}
    return _normalize_mode(runtime_policy.get("runtime_assignment_mode"))


def selected_agent_ids(workspace_execution_view: dict[str, Any] | None) -> set[str]:
    return {
        str(binding.get("source_entity_id") or "").strip()
        for binding in _bindings_for_kind(workspace_execution_view, "agent")
        if str(binding.get("source_entity_id") or "").strip()
    }


def selected_runtime_target_ids(workspace_execution_view: dict[str, Any] | None) -> set[str]:
    return {
        str(binding.get("source_entity_id") or "").strip()
        for binding in _bindings_for_kind(workspace_execution_view, "runtime")
        if str(binding.get("source_entity_id") or "").strip()
    }


def default_agent_binding(workspace_execution_view: dict[str, Any] | None) -> dict[str, Any] | None:
    normalized_view = normalize_workspace_execution_view(workspace_execution_view)
    if normalized_view is None:
        return None
    default_key = str((normalized_view.get("default_binding_keys") or {}).get("agent") or "").strip()
    if not default_key:
        return None
    for binding in _bindings_for_kind(normalized_view, "agent"):
        if str(binding.get("binding_key") or "").strip() == default_key:
            return binding if str(binding.get("source_entity_id") or "").strip() else None
    return None


AGENT_NOT_ALLOWED_DETAIL = "Selected agent is not allowed by the project assignment policy"
RUNTIME_NOT_ALLOWED_DETAIL = "Selected runtime is not allowed by the project assignment policy"


def is_agent_allowed(workspace_execution_view: dict[str, Any] | None, *, agent_id: str) -> bool:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id or agent_assignment_mode(workspace_execution_view) != "selected_only":
        return True
    return normalized_agent_id in selected_agent_ids(workspace_execution_view)


def is_runtime_allowed(workspace_execution_view: dict[str, Any] | None, *, runtime_target_id: str) -> bool:
    normalized_runtime_target_id = str(runtime_target_id or "").strip()
    if not normalized_runtime_target_id or runtime_assignment_mode(workspace_execution_view) != "selected_only":
        return True
    return normalized_runtime_target_id in selected_runtime_target_ids(workspace_execution_view)


def require_agent_allowed(workspace_execution_view: dict[str, Any] | None, *, agent_id: str) -> None:
    if not is_agent_allowed(workspace_execution_view, agent_id=agent_id):
        raise HTTPException(status_code=403, detail=AGENT_NOT_ALLOWED_DETAIL)


def require_runtime_allowed(workspace_execution_view: dict[str, Any] | None, *, runtime_target_id: str) -> None:
    if not is_runtime_allowed(workspace_execution_view, runtime_target_id=runtime_target_id):
        raise HTTPException(status_code=403, detail=RUNTIME_NOT_ALLOWED_DETAIL)


__all__ = [
    "AGENT_NOT_ALLOWED_DETAIL",
    "RUNTIME_NOT_ALLOWED_DETAIL",
    "agent_assignment_mode",
    "default_agent_binding",
    "is_agent_allowed",
    "is_runtime_allowed",
    "require_agent_allowed",
    "require_runtime_allowed",
    "runtime_assignment_mode",
    "selected_agent_ids",
    "selected_runtime_target_ids",
]
