"""``GET /api/v1/admin/connection-types``: the connection types, from the named-connection descriptors."""

from __future__ import annotations

from typing import Any

from app.services.connector_auth.atlassian_modes import AUTH_MODES as ATLASSIAN_AUTH_MODES
from app.services.connector_auth.atlassian_modes import BITBUCKET_AUTH_MODES

from ..connector_auth.servicenow import AUTH_MODES as SERVICENOW_AUTH_MODES
from ..named_connections.descriptor import ConnectorDescriptor
from ..named_connections.descriptors import DESCRIPTORS, descriptor_of, routed_tool_names
from .auth_fields import KIND_NONE, KIND_TOKEN, PUBLIC_TYPES, field_kinds
from .contract import USE_AGENT_TOOLS, USE_KNOWLEDGE, USE_REPOSITORIES, USE_TICKETS

SCOPE_KEYS = {
    "jira": "projects", "confluence": "spaces", "servicenow": "tables",
    "bitbucket": "repositories", "github": "repositories", "gitlab": "repositories",
}
# Where a use stores the scope key's items: Knowledge source scope / intake filters (by type).
KNOWLEDGE_SCOPE_FIELDS = {"jira": "project_keys", "confluence": "spaces", "servicenow": "tables"}
TICKET_SCOPE_FIELDS = {"jira": "project_keys", "servicenow": "tables"}
KNOWLEDGE_TYPES = frozenset({"jira", "confluence", "servicenow", "kubernetes", "bitbucket", "github", "gitlab"})
TICKET_TYPES = frozenset({"jira", "servicenow"})
REPOSITORY_TYPES = frozenset({"bitbucket", "github", "gitlab"})
_FORM_AUTH_KINDS = {"atlassian_auth": ATLASSIAN_AUTH_MODES, "servicenow_auth": SERVICENOW_AUTH_MODES,
                    "bitbucket_auth": BITBUCKET_AUTH_MODES}


def ticket_states() -> list[dict[str, str]]:
    from ..secure_work.workflow_mapping import DEFAULT_WORKFLOW_STATES

    return [{"key": state["key"], "label": state["label"]} for state in DEFAULT_WORKFLOW_STATES]


def ticket_state_keys() -> frozenset[str]:
    return frozenset(state["key"] for state in ticket_states())


def uses_of(connection_type: str) -> list[str]:
    uses = []
    if connection_type in KNOWLEDGE_TYPES:
        uses.append(USE_KNOWLEDGE)
    if connection_type in TICKET_TYPES:
        uses.append(USE_TICKETS)
    if routed_tool_names(connection_type):
        uses.append(USE_AGENT_TOOLS)
    if connection_type in REPOSITORY_TYPES:
        uses.append(USE_REPOSITORIES)
    return uses


def auth_kinds(descriptor: ConnectorDescriptor) -> list[str]:
    modes = _FORM_AUTH_KINDS.get(descriptor.form)
    if modes is not None:
        return list(modes)
    if not descriptor.secret_fields:
        return [KIND_NONE]
    return [KIND_TOKEN, KIND_NONE] if descriptor.connector in PUBLIC_TYPES else [KIND_TOKEN]


def auth_mode_field(descriptor: ConnectorDescriptor) -> str | None:
    return next((item.name for item in descriptor.fields if item.name.endswith("_auth_mode")), None)


def connection_type(descriptor: ConnectorDescriptor) -> dict[str, Any]:
    kinds = auth_kinds(descriptor)
    applies = field_kinds(descriptor, kinds, auth_mode_field(descriptor))  # per field: its sign-in kinds
    entry: dict[str, Any] = {
        "type": descriptor.connector,
        "label": descriptor.label,
        "auth_kinds": kinds,
        "access_fields": [
            {"key": item.name, "label": item.label, "required": applies[item.name]["required"],
             "secret": item.secret, "kind": item.kind, "options": list(item.options),
             "placeholder": item.placeholder, "auth_kinds": applies[item.name]["auth_kinds"]}
            for item in descriptor.fields
        ],
        "uses": uses_of(descriptor.connector),
        "scope_key": SCOPE_KEYS.get(descriptor.connector),
        "testable": descriptor.testable,
    }
    if descriptor.allowlist is not None:
        # The keys a connection binds (``bound_scopes``) and what the Workspace's own list means when empty.
        entry["binding"] = {**descriptor.binding.public(), "allowlist_field": descriptor.allowlist.field,
                            "serves_unlisted": descriptor.allowlist.serves_unlisted}
    if descriptor.connector in TICKET_TYPES:
        entry["ticket_states"] = ticket_states()
    return entry


def list_connection_types() -> list[dict[str, Any]]:
    return [connection_type(descriptor) for descriptor in DESCRIPTORS.values()]


def require_type(raw: object) -> ConnectorDescriptor | None:
    return descriptor_of(raw) if isinstance(raw, str) else None


__all__ = [
    "KNOWLEDGE_SCOPE_FIELDS",
    "SCOPE_KEYS",
    "TICKET_SCOPE_FIELDS",
    "auth_mode_field",
    "connection_type",
    "list_connection_types",
    "require_type",
    "ticket_state_keys",
    "ticket_states",
    "uses_of",
]
