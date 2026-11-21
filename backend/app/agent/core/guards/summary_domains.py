"""Summary-domain helpers for agent execution."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt


def _get_default_config():
    from ....services.system_config.tool_domains import DEFAULT_AGENT_TOOL_DOMAIN_CONFIG
    return DEFAULT_AGENT_TOOL_DOMAIN_CONFIG


def domains_for_tool_name(tool_name: str, tool_domain_config: dict[str, Any] | None = None) -> set[str]:
    if tool_domain_config and isinstance(tool_domain_config.get("summary_tool_domains"), dict):
        override = tool_domain_config["summary_tool_domains"].get(tool_name)
        if isinstance(override, (list, set, tuple)):
            return {str(item) for item in override if str(item).strip()}
    return {
        str(item)
        for item in _get_default_config()["summary_tool_domains"].get(tool_name, [])
        if str(item).strip()
    }


def summary_domains_satisfied_by_result(
    tool_name: str,
    result: dict[str, Any] | None,
    tool_domain_config: dict[str, Any] | None = None,
) -> set[str]:
    if not isinstance(result, dict) or result.get("error"):
        return set()
    domains = domains_for_tool_name(tool_name, tool_domain_config)
    satisfying_tools = {
        key: {str(item) for item in values if str(item).strip()}
        for key, values in _get_default_config()["summary_domain_satisfying_tools"].items()
    }
    if tool_domain_config and isinstance(tool_domain_config.get("summary_domain_satisfying_tools"), dict):
        satisfying_tools = {
            str(domain): {str(item) for item in (tools or []) if str(item).strip()}
            for domain, tools in tool_domain_config["summary_domain_satisfying_tools"].items()
            if isinstance(tools, (list, set, tuple))
        }
    satisfied: set[str] = set()
    for domain in domains:
        if tool_name in satisfying_tools.get(domain, set()):
            satisfied.add(domain)
    return satisfied


def missing_summary_domains(required_domains: set[str], covered_domains: set[str]) -> list[str]:
    return sorted(required_domains - covered_domains)


def build_summary_domain_reminder(missing_domains: list[str]) -> str:
    pretty_names = ", ".join(missing_domains)
    return render_prompt("guard.summary.missing_domains", pretty_names=pretty_names)
