"""Scenario profile fields that are not supported: a write that carries one is refused.

- ``match_config.keywords`` and ``match_config.message_patterns``: prompt matchers. Scenario
  profiles never match prompt text; they match route reasons and required domains;
- ``planner_config.include_tools``, ``planner_config.tool_allowlist``, ``planner_config.blocked_tools``
  and ``execution_config.blocked_tools``: the tool surface comes only from the explicit sources in
  ``agent/core/context/turn_tool_surface.py``.

A create or update that carries any of them, with any value (also ``[]`` or ``null``), is refused
before anything is written: HTTP 422, ``detail = {"code": "field_unsupported", "keys": [...], "message": ...}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

PROMPT_MATCH_KEYS = ("keywords", "message_patterns")
UNSUPPORTED_SCENARIO_FIELDS: dict[str, tuple[str, ...]] = {
    "match_config": PROMPT_MATCH_KEYS,
    "planner_config": ("include_tools", "tool_allowlist", "blocked_tools"),
    "execution_config": ("blocked_tools",),
}


def unsupported_scenario_field_keys(payload: Any) -> list[str]:
    """The unsupported keys a scenario profile payload carries, in ``<config>.<key>`` form."""
    if not isinstance(payload, dict):
        return []
    keys: list[str] = []
    for config_name, unsupported_keys in UNSUPPORTED_SCENARIO_FIELDS.items():
        config = payload.get(config_name)
        if isinstance(config, dict):
            keys.extend(f"{config_name}.{key}" for key in unsupported_keys if key in config)
    return sorted(keys)


def refuse_unsupported_scenario_fields(payload: Any) -> None:
    keys = unsupported_scenario_field_keys(payload)
    if keys:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "field_unsupported",
                "keys": keys,
                "message": (
                    "Scenario profiles no longer match prompt text or set tools. Match on route reasons and "
                    "required domains; the tool surface comes from the selected workflow, the agent definition "
                    "or the Workspace tool policy."
                ),
            },
        )


__all__ = [
    "PROMPT_MATCH_KEYS",
    "UNSUPPORTED_SCENARIO_FIELDS",
    "refuse_unsupported_scenario_fields",
    "unsupported_scenario_field_keys",
]
