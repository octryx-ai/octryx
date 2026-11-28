"""Where an Engineering Knowledge migration target comes from: explicit sources only."""

from __future__ import annotations

from typing import Any

from ._runtime_types import TARGET_SOURCE_REQUEST, EngineeringUpgradeTarget


def _version_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip() and str(item).strip()
    }


def upgrade_target_from_request(params: dict[str, Any] | None) -> EngineeringUpgradeTarget | None:
    values = params if isinstance(params, dict) else {}
    stack_key = str(values.get("stack_key") or "").strip()
    target_versions = _version_mapping(values.get("target_versions"))
    if not stack_key and not target_versions:
        return None
    return EngineeringUpgradeTarget(
        stack_key=stack_key,
        target_versions=target_versions,
        source_versions=_version_mapping(values.get("source_versions")),
        source=TARGET_SOURCE_REQUEST,
    )


__all__ = ["upgrade_target_from_request"]
