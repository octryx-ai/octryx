from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..system_config.values import get_system_config_value
from .registry import is_supported_strategy

DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY = "tool_result_compression.default_compressors"


def _copy_default_compressor_catalog(defaults: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for tool_name, payload in defaults.items():
        catalog[str(tool_name)] = {
            "strategy": str(payload.get("strategy") or "").strip(),
            "config": copy.deepcopy(payload.get("config") if isinstance(payload.get("config"), dict) else {}),
            "is_active": bool(payload.get("is_active", True)),
        }
    return catalog


def _coerce_governed_compressor_overrides(raw_value: str | None) -> dict[str, dict[str, Any]]:
    if not raw_value:
        return {}
    try:
        raw_payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw_payload, dict):
        return {}

    overrides: dict[str, dict[str, Any]] = {}
    for tool_name, payload in raw_payload.items():
        normalized_tool_name = str(tool_name or "").strip()
        if not normalized_tool_name or not isinstance(payload, dict):
            continue
        override: dict[str, Any] = {}

        strategy = str(payload.get("strategy") or "").strip()
        if strategy and is_supported_strategy(strategy):
            override["strategy"] = strategy

        config = payload.get("config")
        if isinstance(config, dict):
            override["config"] = copy.deepcopy(config)

        is_active = payload.get("is_active")
        if isinstance(is_active, bool):
            override["is_active"] = is_active

        if override:
            overrides[normalized_tool_name] = override
    return overrides


async def get_effective_default_compressor_catalog(
    db: AsyncSession,
    *,
    defaults: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog = _copy_default_compressor_catalog(defaults)
    overrides = _coerce_governed_compressor_overrides(
        await get_system_config_value(db, DEFAULT_COMPRESSOR_GOVERNANCE_CONFIG_KEY)
    )
    for tool_name, override in overrides.items():
        if tool_name not in catalog:
            continue
        base = catalog[tool_name]
        config = dict(base.get("config") or {})
        override_config = override.get("config")
        if isinstance(override_config, dict):
            config.update(override_config)
        catalog[tool_name] = {
            "strategy": str(override.get("strategy") or base["strategy"]).strip(),
            "config": config,
            "is_active": bool(override.get("is_active", base["is_active"])),
        }
    return catalog


async def get_effective_default_compressor_definition(
    db: AsyncSession,
    *,
    defaults: dict[str, dict[str, Any]],
    tool_name: str,
) -> dict[str, Any] | None:
    catalog = await get_effective_default_compressor_catalog(db, defaults=defaults)
    return catalog.get(tool_name)
