"""The registry of connector descriptors: the only place a connector type is added."""

from __future__ import annotations

from functools import cache

from ..descriptor import ConnectorDescriptor
from .atlassian import CONFLUENCE, JIRA
from .aws import AWS
from .ci import JENKINS
from .cloud import AZURE, GCP
from .kubernetes import KUBERNETES
from .observability import GRAFANA, LOKI, PROMETHEUS
from .scm import BITBUCKET, GITHUB, GITLAB
from .servicenow import SERVICENOW

DESCRIPTORS: dict[str, ConnectorDescriptor] = {
    descriptor.connector: descriptor
    for descriptor in (
        CONFLUENCE, JIRA, SERVICENOW, KUBERNETES, AWS, BITBUCKET, GITHUB, GITLAB, GRAFANA, LOKI, PROMETHEUS, AZURE,
        GCP, JENKINS,
    )
}


# Connectors whose connection serves platform services only (no agent tool of its own routes through it): Jenkins
# backs Coding's CI runs and the execution of approved CI actions.
SERVICE_ONLY_CONNECTORS = frozenset({"jenkins"})


def descriptor_of(connector: object) -> ConnectorDescriptor | None:
    return DESCRIPTORS.get(str(connector or "").strip().lower())


@cache
def _by_tool() -> dict[str, str]:
    from ...tool_config import get_default_connector_for_tool
    from ...tool_config.presets import TOOL_CONFIG_PRESETS

    claims: dict[str, set[str]] = {}
    for connector, descriptor in DESCRIPTORS.items():
        preset_tools = {tool.get("name") for tool in TOOL_CONFIG_PRESETS.get(connector, {}).get("tools", [])}
        for tool_name in {*preset_tools, *descriptor.tool_names}:
            declared = tool_name in descriptor.tool_names
            if tool_name and (declared or get_default_connector_for_tool(tool_name) == connector):
                claims.setdefault(tool_name, set()).add(connector)
    # A tool two connectors claim is routed by neither (it names no single account).
    return {tool_name: next(iter(owners)) for tool_name, owners in claims.items() if len(owners) == 1}


def descriptor_for_tool(tool_name: str) -> ConnectorDescriptor | None:
    """The descriptor of the connector whose account a tool call uses; ``None``: not a routed tool."""
    connector = _by_tool().get(str(tool_name or ""))
    return DESCRIPTORS.get(connector) if connector else None


def shared_claimants(tool_name: str) -> tuple[ConnectorDescriptor, ...]:
    """The connectors serving a shared tool (routed by the call's ``provider``), in registry order."""
    return tuple(descriptor for descriptor in DESCRIPTORS.values() if tool_name in descriptor.shared_tools)


def routed_tool_names(connector: str) -> frozenset[str]:
    return frozenset(name for name, owner in _by_tool().items() if owner == connector)


__all__ = ["DESCRIPTORS", "descriptor_for_tool", "descriptor_of", "routed_tool_names", "shared_claimants"]
