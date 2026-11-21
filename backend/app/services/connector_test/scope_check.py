"""Configured versus visible: the scope part of an admin connection test.

After a successful test, a connector whose descriptor declares a ``visible_scopes`` probe lists what the
account can see and compares it with the keys the tested config serves (``descriptor.default_keys``: the
allowlist of the default entry, or the bound keys of a named connection, whose test config carries them as its
allowlist). Each configured key the account cannot see is a warning naming the key ("Space RT is configured but
not visible to this account."), so swapped accounts show up in the test, not in the first refused call. The
result stays ``ok`` (the connection works); ``scope_warning`` marks it. Generic over descriptors: no connector
name is branched on here.

Only admin tests run it (``run_connector_connection_test(..., scope_check=True)``); the background health
worker does not, so periodic checks send no extra requests.
"""

from __future__ import annotations

from typing import Any

from ..named_connections.descriptors import descriptor_of
from .visible_scopes import MAX_VISIBLE

MAX_SHOWN = 200


async def check_scopes(tool_name: str, config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any] | None:
    """The comparison, or ``None`` when the connector declares no probe or there is nothing to compare."""
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
    """The test result with the comparison, a warning per configured key the account cannot see."""
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
