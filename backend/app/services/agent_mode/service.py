"""Run modes as code-defined labels.

A run mode (``diagnosis``, ``change``, ``coding`` …) names how a turn behaves; it grants nothing. The run
capability class decides what a run may do (``services/run_capability``), Policies decide what is
forbidden. The modes are the shipped definitions in ``agent/runtime_defaults.py``, so resolving one never reads or
writes the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...agent.runtime_defaults import (
    DEFAULT_AGENT_MODE_KEY,
    SYSTEM_AGENT_MODE_DEFINITIONS,
    get_system_agent_mode_definition,
)
from .normalization import normalize_agent_mode_key, normalize_capability_type


@dataclass(slots=True)
class ResolvedAgentMode:
    key: str
    name: str
    description: str
    capability_type: str
    prompt_instructions: str
    is_active: bool
    is_system: bool


def _resolved(key: str) -> ResolvedAgentMode:
    definition = get_system_agent_mode_definition(key) or get_system_agent_mode_definition(DEFAULT_AGENT_MODE_KEY)
    assert definition is not None  # the default is always shipped
    return ResolvedAgentMode(
        key=definition.key,
        name=definition.name,
        description=definition.description,
        capability_type=normalize_capability_type(definition.capability_type),
        prompt_instructions=definition.prompt_instructions,
        is_active=True,
        is_system=True,
    )


def serialize_agent_mode(mode: ResolvedAgentMode) -> dict[str, object]:
    return {
        "id": mode.key,
        "key": mode.key,
        "name": mode.name,
        "description": mode.description or "",
        "capability_type": mode.capability_type,
        "prompt_instructions": mode.prompt_instructions or "",
        "is_active": True,
        "is_system": True,
    }


def known_agent_mode_keys() -> frozenset[str]:
    return frozenset(definition.key for definition in SYSTEM_AGENT_MODE_DEFINITIONS)


def list_agent_modes() -> list[ResolvedAgentMode]:
    """Every shipped run mode."""
    return [_resolved(definition.key) for definition in SYSTEM_AGENT_MODE_DEFINITIONS]


async def resolve_agent_mode(db: Any, mode_key: str | None) -> ResolvedAgentMode:
    """The shipped run mode for *mode_key*; an empty key is the configured default (read only, never
    written), an unknown key the shipped default."""
    requested = str(mode_key or "").strip()
    if not requested and db is not None:
        from ..system_config.values import get_agent_default_mode_key

        requested = await get_agent_default_mode_key(db)
    return _resolved(normalize_agent_mode_key(requested or DEFAULT_AGENT_MODE_KEY))


__all__ = [
    "ResolvedAgentMode",
    "known_agent_mode_keys",
    "list_agent_modes",
    "resolve_agent_mode",
    "serialize_agent_mode",
]
