"""Connector writes from a chat, each one confirmed by the person."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ...tools.definitions import get_all_definitions, get_tool_definition_metadata
from .classes import run_capability_state

CHAT_CONNECTOR_WRITES_KEY = "chat_connector_writes"
CONNECTOR_OWNER = "connector"
REST_OWNER = "dynamic_rest"
#: Owners whose write tools reach an external system through an admin-configured connection.
CONNECTOR_WRITE_OWNERS = frozenset({CONNECTOR_OWNER, REST_OWNER})
WRITE_RISK = "write"


def is_chat_connector_write_tool(tool_name: str) -> bool:
    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    return metadata.owner_type in CONNECTOR_WRITE_OWNERS and metadata.risk == WRITE_RISK


def chat_connector_writes_enabled(context: Any) -> bool:
    state = run_capability_state(context)
    return bool(state) and state.get("enforced") is True and state.get(CHAT_CONNECTOR_WRITES_KEY) is True


def chat_connector_write_permitted(tool_name: str, context: Any) -> bool:
    return chat_connector_writes_enabled(context) and is_chat_connector_write_tool(tool_name)


# Built-in writes that keep their own per-command policy: the CLI runtime classifies each command and asks for the
# writing ones (``runtime_impl/_runtime_workspace_cli``), so a chat's read-only ``kubectl get`` is not asked twice.
_OWN_POLICY_PLATFORM_WRITES = frozenset({"run_cli_command"})


def chat_platform_write_needs_confirmation(tool_name: str, context: Any) -> bool:
    name = str(tool_name or "").strip()
    metadata = get_tool_definition_metadata(name)
    return (chat_connector_writes_enabled(context) and metadata.owner_type not in CONNECTOR_WRITE_OWNERS
            and metadata.risk in {WRITE_RISK, "admin"} and name not in _OWN_POLICY_PLATFORM_WRITES)


@lru_cache(maxsize=1)
def chat_connector_write_tool_names() -> tuple[str, ...]:
    return tuple(sorted(name for name in get_all_definitions() if is_chat_connector_write_tool(name)))


__all__ = [
    "CHAT_CONNECTOR_WRITES_KEY",
    "chat_connector_write_permitted",
    "chat_connector_write_tool_names",
    "chat_connector_writes_enabled",
    "chat_platform_write_needs_confirmation",
    "is_chat_connector_write_tool",
]
