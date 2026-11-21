"""The contract of a named connection: which connectors, which fields, which names and bound scopes.

A named connection is one more account of a connector in one scope (a Workspace, or global): the
connector's *connection unit* (the fields its descriptor declares, ``descriptor.py``: target, auth,
principal, options and secret refs) plus ``bound_scopes``, the keys it serves (Confluence space keys,
Jira project keys, ServiceNow tables, Kubernetes clusters, ...; the descriptor's binding). Everything
else (allowlists of pages, limits) comes from the connector's default entry; a descriptor may add settings that
describe how its instance is read (ServiceNow's API style and Scripted REST paths) to the unit.

The connector's single tool entry is the implicit connection named ``default``. A named
connection may not use that name, and a scope key is bound by at most one named connection per
connector and scope (refused at save, never resolved by order).

Secrets of a named connection are stored in the secret store under the field name
``<field>#<connection id>`` (:func:`named_secret_field`), so a ref copied from another connection, the
default entry or another Workspace never resolves (the store refuses a ref outside its expected tool,
field and project).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .descriptor import ConnectorDescriptor
from .descriptors import DESCRIPTORS, descriptor_of

CONFLUENCE = "confluence"
JIRA = "jira"
SERVICENOW = "servicenow"
NAMED_CONNECTION_CONNECTORS = tuple(DESCRIPTORS)
DEFAULT_CONNECTION_NAME = "default"
MAX_BOUND_SCOPES = 100
MAX_CONNECTIONS_PER_SCOPE = 50

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

CODE_CONNECTOR_UNSUPPORTED = "named_connection_connector_unsupported"
CODE_NAME_INVALID = "named_connection_name_invalid"
CODE_NAME_RESERVED = "named_connection_name_reserved"
CODE_NAME_TAKEN = "named_connection_name_taken"
CODE_SCOPES_INVALID = "named_connection_scopes_invalid"
CODE_SCOPE_BOUND_TWICE = "named_connection_scope_bound_twice"
CODE_TOO_MANY = "named_connection_limit_reached"


class NamedConnectionError(ValueError):
    """A refused named connection; ``code`` is fixed and the message names fields and keys, never values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NamedConnection:
    """One stored named connection; ``config`` holds secret refs, never a secret value."""

    id: str
    tool_name: str
    project_id: str | None
    name: str
    config: dict = field(repr=False)
    bound_scopes: frozenset[str] = frozenset()


def require_descriptor(tool_name: object) -> ConnectorDescriptor:
    descriptor = descriptor_of(tool_name)
    if descriptor is None:
        labels = ", ".join(item.label for item in DESCRIPTORS.values())
        raise NamedConnectionError(CODE_CONNECTOR_UNSUPPORTED, f"Named connections exist for {labels}.")
    return descriptor


def require_connector(tool_name: object) -> str:
    return require_descriptor(tool_name).connector


def editable_fields(tool_name: str) -> tuple[str, ...]:
    """The non-secret fields of a named connection, as its connector's descriptor declares them."""
    return require_descriptor(tool_name).editable_fields


def secret_fields(tool_name: str) -> tuple[str, ...]:
    descriptor = descriptor_of(tool_name)
    return descriptor.secret_fields if descriptor is not None else ()


def connection_keys(tool_name: str) -> frozenset[str]:
    """Every key a named connection replaces in the default entry: its fields, secrets and secret refs."""
    return require_descriptor(tool_name).unit_keys


def named_secret_field(field_name: str, connection_id: str) -> str:
    """The secret-store field name of one named connection's secret: bound to that connection alone."""
    return f"{field_name}#{connection_id}"


def scope_key(tool_name: str, value: object) -> str:
    """The canonical form a bound scope is stored and compared in (the descriptor's binding case)."""
    descriptor = descriptor_of(tool_name)
    return descriptor.scope_key(value) if descriptor is not None else str(value or "").strip()


def validate_name(raw: object) -> str:
    name = raw.strip() if isinstance(raw, str) else ""
    if not NAME.fullmatch(name):
        raise NamedConnectionError(
            CODE_NAME_INVALID, "name: 1-64 letters, digits, '.', '_' or '-', starting with a letter or digit."
        )
    if name.lower() == DEFAULT_CONNECTION_NAME:
        raise NamedConnectionError(CODE_NAME_RESERVED, "The name 'default' is the connector's own entry.")
    return name


def validate_bound_scopes(tool_name: str, raw: object) -> tuple[str, ...]:
    """The canonical, de-duplicated scope keys in their given order; at least one."""
    binding = require_descriptor(tool_name).binding
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    if not isinstance(raw, list | tuple) or not raw or len(raw) > MAX_BOUND_SCOPES:
        raise NamedConnectionError(CODE_SCOPES_INVALID, f"bound_scopes: 1-{MAX_BOUND_SCOPES} keys.")
    keys: list[str] = []
    for entry in raw:
        if not binding.valid(entry):
            raise NamedConnectionError(CODE_SCOPES_INVALID, "bound_scopes: a key has an invalid form.")
        key = binding.canonical(entry)
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def bound_elsewhere(
    tool_name: str, keys: Iterable[str], others: Iterable[NamedConnection]
) -> list[tuple[str, str]]:
    """``(scope key, other connection name)`` for every key another connection of the same scope binds."""
    clashes = []
    for other in others:
        for key in keys:
            if scope_key(tool_name, key) in other.bound_scopes:
                clashes.append((key, other.name))
    return sorted(clashes)


__all__ = [
    "CODE_CONNECTOR_UNSUPPORTED",
    "CODE_NAME_INVALID",
    "CODE_NAME_RESERVED",
    "CODE_NAME_TAKEN",
    "CODE_SCOPES_INVALID",
    "CODE_SCOPE_BOUND_TWICE",
    "CODE_TOO_MANY",
    "CONFLUENCE",
    "DEFAULT_CONNECTION_NAME",
    "JIRA",
    "MAX_BOUND_SCOPES",
    "MAX_CONNECTIONS_PER_SCOPE",
    "NAMED_CONNECTION_CONNECTORS",
    "SERVICENOW",
    "NamedConnection",
    "NamedConnectionError",
    "bound_elsewhere",
    "connection_keys",
    "editable_fields",
    "named_secret_field",
    "require_connector",
    "require_descriptor",
    "scope_key",
    "secret_fields",
    "validate_bound_scopes",
    "validate_name",
]
