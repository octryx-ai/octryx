"""Tool-domain configuration helpers for agent routing."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from .constants import (
    AGENT_TOOL_DOMAIN_CONFIG_KEY,
    DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS,
    DEFAULT_SUMMARY_DOMAIN_TOOL_ALLOWLISTS,
    DEFAULT_SUMMARY_TOOL_DOMAINS,
)
from .values import get_system_config_value


def _normalized_list_mapping(value: object, *, defaults: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {key: list(items) for key, items in defaults.items()}
    if not isinstance(value, dict):
        return merged
    for key, items in value.items():
        if isinstance(items, (list, tuple, set)):
            merged[str(key)] = [str(item) for item in items if str(item).strip()]
    return merged


def _normalized_set_mapping(value: object, *, defaults: dict[str, set[str]]) -> dict[str, list[str]]:
    merged = {key: sorted(items) for key, items in defaults.items()}
    if not isinstance(value, dict):
        return merged
    for key, items in value.items():
        if isinstance(items, (list, tuple, set)):
            merged[str(key)] = [str(item) for item in items if str(item).strip()]
    return merged


def get_default_agent_tool_domain_config() -> dict[str, dict[str, list[str]]]:
    from .constants import get_domain_tool_allowlists

    return {
        "domain_tool_allowlists": _normalized_list_mapping(
            None,
            defaults=get_domain_tool_allowlists(),
        ),
        "summary_domain_tool_allowlists": _normalized_list_mapping(
            None,
            defaults=DEFAULT_SUMMARY_DOMAIN_TOOL_ALLOWLISTS,
        ),
        "summary_tool_domains": _normalized_set_mapping(
            None,
            defaults=DEFAULT_SUMMARY_TOOL_DOMAINS,
        ),
        "summary_domain_satisfying_tools": _normalized_set_mapping(
            None,
            defaults=DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS,
        ),
    }


DEFAULT_AGENT_TOOL_DOMAIN_CONFIG = get_default_agent_tool_domain_config()


def normalize_agent_tool_domain_config(value: object) -> dict[str, dict[str, list[str]]]:
    from .constants import get_domain_tool_allowlists

    if not isinstance(value, dict):
        return get_default_agent_tool_domain_config()
    return {
        "domain_tool_allowlists": _normalized_list_mapping(
            value.get("domain_tool_allowlists"),
            defaults=get_domain_tool_allowlists(),
        ),
        "summary_domain_tool_allowlists": _normalized_list_mapping(
            value.get("summary_domain_tool_allowlists"),
            defaults=DEFAULT_SUMMARY_DOMAIN_TOOL_ALLOWLISTS,
        ),
        "summary_tool_domains": _normalized_set_mapping(
            value.get("summary_tool_domains"),
            defaults=DEFAULT_SUMMARY_TOOL_DOMAINS,
        ),
        "summary_domain_satisfying_tools": _normalized_set_mapping(
            value.get("summary_domain_satisfying_tools"),
            defaults=DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS,
        ),
    }


async def get_agent_tool_domain_config(db: AsyncSession) -> dict[str, dict[str, list[str]]]:
    raw_value = await get_system_config_value(db, AGENT_TOOL_DOMAIN_CONFIG_KEY)
    if not raw_value:
        return get_default_agent_tool_domain_config()
    try:
        payload = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = {}
    return normalize_agent_tool_domain_config(payload)


__all__ = [
    "DEFAULT_AGENT_TOOL_DOMAIN_CONFIG",
    "get_agent_tool_domain_config",
    "get_default_agent_tool_domain_config",
    "normalize_agent_tool_domain_config",
]
