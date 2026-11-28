"""A gateway alias's declared capabilities win over the catalog probe."""

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
    if not declared or not isinstance(row.capabilities_json, dict):
        return
    row.capabilities_json = {**row.capabilities_json, **declared}


__all__ = ["apply_declared", "declared_capabilities", "with_declared_capabilities"]
