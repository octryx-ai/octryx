"""Connector writes from a chat, each one confirmed by the person.

A chat turn outside a workflow run's phase runs ``read_only``, and its governed default tool set holds only connector
reads. Alone, that means a Workspace whose Jira Cloud connection has agent tools level ``write`` still offers the chat
only ``get_jira_ticket`` / ``search_jira_tickets`` / ``list_jira_projects``, and the chat cannot create the Epic the
person asks for. Work must be startable from the chat.

So a chat turn (no workflow run phase, no parent run, no declared programmatic origin) keeps its ``read_only`` class
for everything else, and additionally:

- is offered the **connector write tools** (connector-owned, risk ``write``) next to its governed default set; the
  connections still decide which survive (connector activation, agent tools level ``write``, disabled connection);
- may dispatch such a tool although it needs ``deliver`` (``escalation.capability_dispatch_refusal``,
  ``surface_admission.tool_violations``), and the "high-risk connector tool needs an explicit tool-policy allow"
  rule is answered by the person's confirmation instead (Workspace deny lists still refuse);
- needs the person's confirmation before it runs (``tool_approval_gate``, rule ``chat_connector_write``): no platform
  exemption and no standing "always" rule waives it, and the confirmation names the tool, the connection it writes
  through and every field it writes. That is one write plan per request, confirmed once, that covers every write it
  names (``chat_write_plan.py``).

A custom REST write (``rest__…``, owner ``dynamic_rest``) is a connector
write in this sense: an admin defined it on an external API, the person's REST grants decide who may call it, and it
goes through the same write plan.

Reads stay free. Workspace edits, builds, pushes and MCP writes stay with workflow runs, and workflow-run phases,
schedules, flows, workers and sub-agents keep their declared class unchanged.
"""

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
    """A connector-owned tool of risk ``write`` (``create_jira_ticket``, ``add_jira_comment``, a REST write ...)."""
    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    return metadata.owner_type in CONNECTOR_WRITE_OWNERS and metadata.risk == WRITE_RISK


def chat_connector_writes_enabled(context: Any) -> bool:
    """Whether the run behind ``context`` is a chat turn that may write through connectors (with confirmation)."""
    state = run_capability_state(context)
    return bool(state) and state.get("enforced") is True and state.get(CHAT_CONNECTOR_WRITES_KEY) is True


def chat_connector_write_permitted(tool_name: str, context: Any) -> bool:
    """A connector write tool called from a chat turn: it may run, after the person confirms this call."""
    return chat_connector_writes_enabled(context) and is_chat_connector_write_tool(tool_name)


# Built-in writes that keep their own per-command policy: the CLI runtime classifies each command and asks for the
# writing ones (``runtime_impl/_runtime_workspace_cli``), so a chat's read-only ``kubectl get`` is not asked twice.
_OWN_POLICY_PLATFORM_WRITES = frozenset({"run_cli_command"})


def chat_platform_write_needs_confirmation(tool_name: str, context: Any) -> bool:
    """A platform write from a chat turn (``work_item_create``, ``work_item_note``, ``memory_remember`` ...).

    Asked for a Jira Epic, a chat can call ``work_item_create`` on its own and make a stray task, so platform writes
    from the chat need the same per-call confirmation as connector writes. Reads stay free.
    """
    name = str(tool_name or "").strip()
    metadata = get_tool_definition_metadata(name)
    return (chat_connector_writes_enabled(context) and metadata.owner_type not in CONNECTOR_WRITE_OWNERS
            and metadata.risk in {WRITE_RISK, "admin"} and name not in _OWN_POLICY_PLATFORM_WRITES)


@lru_cache(maxsize=1)
def chat_connector_write_tool_names() -> tuple[str, ...]:
    """Every connector write tool of the registry, by name (the chat surface adds them; visibility filters)."""
    return tuple(sorted(name for name in get_all_definitions() if is_chat_connector_write_tool(name)))


__all__ = [
    "CHAT_CONNECTOR_WRITES_KEY",
    "chat_connector_write_permitted",
    "chat_connector_write_tool_names",
    "chat_connector_writes_enabled",
    "chat_platform_write_needs_confirmation",
    "is_chat_connector_write_tool",
]
