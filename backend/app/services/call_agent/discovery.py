"""Tool discovery for the CallAgent: which tools exist and which a project has configured."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Plugin-id fragments mapped to connector categories; the first fragment found in a plugin id wins.
_CONNECTOR_FRAGMENTS = (
    "jira",
    "confluence",
    "bitbucket",
    "github",
    "gitlab",
    "linear",
    "datadog",
    "newrelic",
    "pagerduty",
)


def extract_tool_category(tool_name: str) -> str:
    """Return the owning category of a tool from its registry metadata."""
    from ...tools.definitions import get_tool_definition_metadata

    metadata = get_tool_definition_metadata(tool_name)
    if metadata.connector:
        return str(metadata.connector)
    return str(metadata.source or "system")


def _add_tool(groups: dict[str, list[dict]], category: str, tool_name: str, tool_instance: Any) -> None:
    if category not in groups:
        groups[category] = []

    description = getattr(tool_instance, "description", "") or ""
    groups[category].append({
        "name": tool_name,
        "description": description,
    })


def _sort_groups(groups: dict[str, list[dict]]) -> dict[str, list[dict]]:
    for category in groups:
        groups[category].sort(key=lambda t: t["name"])
    return groups


def discover_all_tools() -> dict[str, list[dict]]:
    """Return all available tools, grouped by connector/category."""
    from ...tools.definitions.connector_ownership import SERVICE_ONLY_TOOLS
    from ...tools.registry import TOOL_REGISTRY

    groups: dict[str, list[dict]] = {}

    for tool_name, tool_instance in TOOL_REGISTRY.items():
        if tool_name in SERVICE_ONLY_TOOLS:
            continue
        category = extract_tool_category(tool_name)
        _add_tool(groups, category, tool_name, tool_instance)

    return _sort_groups(groups)


async def _configured_connectors(db: AsyncSession, project_id: str | None) -> set[str]:
    from ...models import ChannelConfig

    configured_connectors: set[str] = set()
    if not project_id:
        return configured_connectors

    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.project_id == project_id,
            ChannelConfig.enabled.is_(True),
        )
    )
    channels = list(result.scalars().all())

    for channel in channels:
        plugin_id = channel.plugin_id.lower()
        for fragment in _CONNECTOR_FRAGMENTS:
            if fragment in plugin_id:
                configured_connectors.add(fragment)
                break
    return configured_connectors


async def discover_configured_tools(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    channel_id: str | None = None,
) -> dict[str, list[dict]]:
    """Return only the tools configured for this project/channel."""
    from ...tools.registry import TOOL_REGISTRY

    configured_connectors = await _configured_connectors(db, project_id)

    groups: dict[str, list[dict]] = {}

    for tool_name, tool_instance in TOOL_REGISTRY.items():
        category = extract_tool_category(tool_name)

        # Skip connector tools that aren't configured
        if category != "system" and category not in configured_connectors:
            continue

        _add_tool(groups, category, tool_name, tool_instance)

    return _sort_groups(groups)
