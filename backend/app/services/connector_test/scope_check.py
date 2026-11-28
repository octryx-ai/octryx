"""Configured versus visible: the scope part of an admin connection test."""

from __future__ import annotations

from typing import Any

from ..named_connections.descriptors import descriptor_of
from .visible_scopes import MAX_VISIBLE

MAX_SHOWN = 200


async def check_scopes(tool_name: str, config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any] | None:
    descriptor = descriptor_of(tool_name)
    if descriptor is None or descriptor.visible_scopes is None:
        return None
    configured = descriptor.default_keys(config)
    visible = await descriptor.visible_scopes(config, configured, httpx_module=httpx_module)
    if visible is None:
        return None
    binding = descriptor.binding
    payload: dict[str, Any] = {
        "label": binding.plural,
        "noun": binding.label,
        "configured": sorted(configured) if configured is not None else None,
        "visible": list(visible.keys[:MAX_SHOWN]),
        "visible_count": len(visible.keys),
        "visible_complete": visible.complete and len(visible.keys) <= MAX_VISIBLE,
        "missing": [],
        "error": visible.error,
        "http_status": visible.http_status,
    }
    if visible.error or configured is None:
        return payload
    seen = {descriptor.scope_key(key) for key in visible.keys}
    payload["missing"] = sorted(
        key for key in configured if descriptor.scope_key(key) not in seen and not visible.direct.get(key, False)
    )
    return payload


def with_scope_check(result: dict[str, Any], check: dict[str, Any] | None) -> dict[str, Any]:
    if check is None:
        return result
    noun = str(check["noun"]).capitalize()
    warnings = [f"{noun} {key} is configured but not visible to this account." for key in check["missing"]]
    merged = {**result, "scope_check": check}
    if warnings:
        merged["scope_warning"] = True
        merged["warnings"] = warnings
        merged["summary"] = f"{result.get('summary', '')} Not visible to this account: {', '.join(check['missing'])}."
    elif check["error"]:
        merged["summary"] = f"{result.get('summary', '')} The visible {check['label'].lower()} could not be listed."
    return merged


__all__ = ["check_scopes", "with_scope_check"]
