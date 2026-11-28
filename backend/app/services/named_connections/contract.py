"""The contract of a named connection: which connectors, which fields, which names and bound scopes."""

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
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class NamedConnection:
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
    return require_descriptor(tool_name).editable_fields


def secret_fields(tool_name: str) -> tuple[str, ...]:
    descriptor = descriptor_of(tool_name)
    return descriptor.secret_fields if descriptor is not None else ()


def connection_keys(tool_name: str) -> frozenset[str]:
    return require_descriptor(tool_name).unit_keys


def named_secret_field(field_name: str, connection_id: str) -> str:
    return f"{field_name}#{connection_id}"


def scope_key(tool_name: str, value: object) -> str:
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
