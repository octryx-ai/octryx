"""A gateway alias's declared capabilities win over the catalog probe.

The admin declares ``capabilities.tools`` / ``capabilities.vision`` on a ``litellm_gateway`` alias. Every catalog
save mirrors the catalog row back into the alias (``model_catalog.alias_mirror``), so copying the probe's
``supports_tools`` into the row would let a probe that does not advertise tools (llama.cpp's server: only
"completion") lower the admin's ``tools: true``, and the gateway would then refuse tool calls
(``capability_not_declared_for_alias``). So the declared value is what the row gets; a probe that says otherwise
is reported as a warning in the sync result and its audit, never applied.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...model_catalog.alias_mirror import alias_entries

CHECKED = (("tools", "supports_tools"), ("vision", "supports_vision"))


def declared_capabilities(provider: Any, model_id: str) -> dict[str, bool]:
    entry = alias_entries(provider).get(model_id)
    capabilities = entry.get("capabilities") if isinstance(entry, Mapping) else None
    if not isinstance(capabilities, Mapping):
        return {}
    return {name: capabilities[name] for name, _ in CHECKED if isinstance(capabilities.get(name), bool)}


def with_declared_capabilities(provider: Any, model_id: str,
                               payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The sync payload with the alias's declared values, and a warning per capability the probe reports otherwise."""
    declared = declared_capabilities(provider, model_id)
    out, warnings = dict(payload), []
    for name, column in CHECKED:
        if name not in declared:
            continue
        probed = payload.get(column)
        if isinstance(probed, bool) and probed != declared[name]:
            warnings.append({"model_id": model_id, "capability": name, "declared": declared[name],
                             "probe": probed})
        out[column] = declared[name]
    out["declared_capabilities"] = declared
    return out, warnings


def apply_declared(row: Any, declared: Mapping[str, bool]) -> None:
    """Keep a catalog row's ``capabilities_json`` (read before the ``supports_*`` columns) on the declared values."""
    if not declared or not isinstance(row.capabilities_json, dict):
        return
    row.capabilities_json = {**row.capabilities_json, **declared}


__all__ = ["apply_declared", "declared_capabilities", "with_declared_capabilities"]
