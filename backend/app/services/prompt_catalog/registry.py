"""The closed registry of prompt catalog keys.

Two kinds of keys:

* **static** keys, declared by the seed modules (``seeds/``), which are the only code copy
  of their texts and are written into the database by the seed step;
* **dynamic** keys whose seed is code that already exists elsewhere: the built-in tool
  descriptions (``tool_catalog``, seeded by the tool definitions) and the Knowledge MCP tool
  descriptions (``mcp_descriptions``, seeded by the server's registrations). They are built
  lazily on first use (their sources import this package) and are not written into the
  database; the code is their last precedence level.

A key exists only when one of these declares it. The admin API, the seed step and the
resolver all read this registry, so a template for an unknown key can be neither created
nor resolved. Building it renders nothing and needs no database.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType

from .contract import REASON_UNKNOWN_KEY, PromptKeySpec, PromptTemplateUnavailableError
from .seeds import all_seed_specs


def _indexed(specs, into: dict[str, PromptKeySpec]) -> None:
    for spec in specs:
        if spec.key in into:
            raise ValueError(f"duplicate prompt catalog key: {spec.key}")
        into[spec.key] = spec


@lru_cache(maxsize=1)
def static_prompt_key_registry() -> Mapping[str, PromptKeySpec]:
    """The seed-module keys only (safe at import time; the seed step writes these)."""
    specs: dict[str, PromptKeySpec] = {}
    _indexed(all_seed_specs(), specs)
    return MappingProxyType(specs)


@lru_cache(maxsize=1)
def prompt_key_registry() -> Mapping[str, PromptKeySpec]:
    from .mcp_descriptions import mcp_description_specs
    from .tool_catalog import tool_description_specs

    specs: dict[str, PromptKeySpec] = dict(static_prompt_key_registry())
    _indexed(tool_description_specs(), specs)
    _indexed(mcp_description_specs(), specs)
    return MappingProxyType(specs)


def prompt_key_spec(key: str) -> PromptKeySpec:
    spec = prompt_key_registry().get(str(key or ""))
    if spec is None:
        raise PromptTemplateUnavailableError(str(key or ""), REASON_UNKNOWN_KEY)
    return spec


def is_known_prompt_key(key: str) -> bool:
    return str(key or "") in prompt_key_registry()


__all__ = ["is_known_prompt_key", "prompt_key_registry", "prompt_key_spec", "static_prompt_key_registry"]
