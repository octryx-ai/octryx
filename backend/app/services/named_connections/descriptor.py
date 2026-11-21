"""The connector descriptor: all one connector type contributes to named connections.

Named connections are one generic model for every connector with credentials or endpoints: one table
(``connector_named_connections``), one resolver (``resolver.py``), one tool router (``tool_routing.py``),
one admin API (``web/routers/panel_named_connections.py``) and one UI component (``NamedConnections.tsx``).
A connector type takes part only through a :class:`ConnectorDescriptor` registered in
``descriptors/__init__.py``; none of those modules branches on a connector name.

A descriptor declares:

- **fields** (:class:`Field`): the connection unit an admin edits, which of them are secrets (stored in the
  secret store under ``<field>#<connection id>``, write-only) and which the UI renders how;
- **binding** (:class:`Binding`): the kind of key a connection is bound to (a space, a cluster, an account),
  its form and canonical case, and whether keys nest (``group/sub/project`` is served by ``group``);
- **request_keys**: the binding keys a tool call names (from its parameters; ``()`` for none);
- **request_params**: optional tool parameters the connector adds so a call can name its key
  (e.g. ``cluster``); every routed tool also gets the generic ``connection`` parameter;
- **allowlist** (:class:`Allowlist`) or **default_key_fields**: which keys the connector's default entry
  serves today, and how a named connection's allowlist is narrowed to its bound keys;
- **unscoped**: what a call without a key does when named connections exist: ``default`` (run on the
  default, whose allowlist no longer holds any bound key) or ``single`` (run on the one candidate; several
  candidates are refused with the list, ``connection_ambiguous``);
- **complete** / **runtime_guard** / **request_guard**: when a unit is complete at save; the check right
  before a call runs on a named connection (a connector whose client would otherwise fall back to a host
  or platform credential refuses instead); a per-call restriction ``(tool_name, config, params)`` of a
  named connection (e.g. its namespaces);
- **usable_field** / **default_usable_fields**: the URL a connection needs, and the other fields that make
  the connector's default entry usable (e.g. a kubeconfig);
- **tool_names** / **shared_tools**: tools routed besides the preset's own list; tools several connectors
  serve (e.g. CI logs of GitHub or GitLab), routed to this connector when the call's ``provider`` names it;
- **visible_scopes**: an optional read-only probe listing the keys the account can see
  (``connector_test/visible_scopes.py``); an admin connection test compares them with the configured or bound
  keys and warns per key the account cannot see (``connector_test/scope_check.py``);
- **form** and **testable**: the UI form kind (``fields`` renders :attr:`fields`; ``atlassian_auth`` and
  ``servicenow_auth`` are the existing sign-in forms with auth modes) and whether the connector has a
  connection test (``connector_test_service.run_connector_connection_test``).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

UNSCOPED_DEFAULT = "default"
UNSCOPED_SINGLE = "single"
FORM_FIELDS = "fields"
CASE_UPPER, CASE_LOWER, CASE_EXACT = "upper", "lower", "exact"
FIELD_KINDS = ("text", "url", "secret", "bool", "list", "select", "int")


class UnitIncompleteError(ValueError):
    """A connection unit that cannot serve a call; ``code`` is fixed, the message names fields only."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Field:
    """One field of a connection unit; ``kind`` ``secret`` is write-only and lives in the secret store."""

    name: str
    label: str
    kind: str = "text"
    required: bool = False
    options: tuple[str, ...] = ()
    placeholder: str = ""

    @property
    def secret(self) -> bool:
        return self.kind == "secret"

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name, "label": self.label, "kind": self.kind, "required": self.required,
            "options": list(self.options), "placeholder": self.placeholder,
        }


@dataclass(frozen=True, slots=True)
class Binding:
    """The keys a connection is bound to: their name, form and canonical case."""

    label: str
    plural: str
    pattern: str
    case: str = CASE_UPPER
    example: str = ""
    hierarchical: bool = False

    def canonical(self, value: object) -> str:
        text = str(value or "").strip()
        if self.case == CASE_UPPER:
            return text.upper()
        if self.case == CASE_LOWER:
            return text.lower()
        return text

    def valid(self, value: object) -> bool:
        return isinstance(value, str) and re.fullmatch(self.pattern, value.strip()) is not None

    def candidates(self, key: str) -> tuple[str, ...]:
        """``key``, then each parent when keys nest (``a/b/c``, ``a/b``, ``a``): the most specific binding wins."""
        if not self.hierarchical:
            return (key,)
        parts = key.split("/")
        return tuple("/".join(parts[:end]) for end in range(len(parts), 0, -1))

    def public(self) -> dict[str, Any]:
        return {
            "label": self.label, "plural": self.plural, "pattern": self.pattern, "case": self.case,
            "example": self.example, "hierarchical": self.hierarchical,
        }


def rule_key(entry: Any) -> str:
    """The key of one allowlist rule: a plain key or a dict rule (``space_key``, ``key``, ``table``)."""
    if isinstance(entry, dict):
        return str(entry.get("space_key") or entry.get("key") or entry.get("table") or "").strip()
    return str(entry or "").strip()


def _key_entry(key: str) -> Any:
    return key


@dataclass(frozen=True, slots=True)
class Allowlist:
    """The default entry's allowlist field: which keys it serves and how a connection's list is narrowed.

    ``serves_unlisted``: an empty list means unrestricted (Jira, ServiceNow) or nothing (Confluence).
    ``single_key_field``: a one-key setting used while the list is empty (``confluence_space_key``).
    ``entry``: the rule a bound key gets in a named connection's list when the default has none for it.
    """

    field: str
    serves_unlisted: bool = True
    single_key_field: str | None = None
    rule_key: Callable[[Any], str] = rule_key
    entry: Callable[[str], Any] = _key_entry
    # A connection's list for its bound keys when one rule per key cannot say it (e.g. a whole owner bound):
    # ``(the keys' rules, bound keys) -> list``; default: the rules.
    narrow: Callable[[list[Any], frozenset[str]], list[Any]] | None = None


def _no_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    return ()


def _always_complete(config: dict) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor:
    """Everything one connector type contributes to named connections (see the module doc)."""

    connector: str
    label: str
    binding: Binding
    fields: tuple[Field, ...]
    usable_field: str
    default_usable_fields: tuple[str, ...] = ()
    request_keys: Callable[[str, dict], Iterable[str]] = _no_keys
    request_params: dict[str, dict] = field(default_factory=dict)
    allowlist: Allowlist | None = None
    default_key_fields: tuple[str, ...] = ()
    unscoped: str = UNSCOPED_SINGLE
    fan_out_tools: frozenset[str] = frozenset()
    result_key: Callable[[Any], str | None] | None = None
    named_drops: tuple[str, ...] = ()
    tool_names: frozenset[str] = frozenset()
    shared_tools: frozenset[str] = frozenset()
    complete: Callable[[dict], None] = _always_complete
    runtime_guard: Callable[[dict], None] | None = None
    request_guard: Callable[[str, dict, dict], str | None] | None = None
    form: str = FORM_FIELDS
    testable: bool = True
    # ``async (config, configured keys | None, *, httpx_module) -> VisibleScopes | None``
    visible_scopes: Callable[..., Awaitable[Any]] | None = None

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields if item.secret)

    @property
    def editable_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields if not item.secret)

    @property
    def unit_keys(self) -> frozenset[str]:
        """Every key a named connection replaces in the default entry: its fields, secrets and secret refs."""
        return frozenset((*(item.name for item in self.fields), *(f"{name}_secret_ref" for name in self.secret_fields)))

    def usable(self, config: dict) -> bool:
        """Whether ``config`` can serve a call at all (its URL, or one of the default's other usable fields)."""
        return any(_set(config.get(name)) for name in (self.usable_field, *self.default_usable_fields))

    def scope_key(self, value: object) -> str:
        return self.binding.canonical(value)

    def default_keys(self, config: dict) -> frozenset[str] | None:
        """The keys the default entry serves by today's rules; ``None``: unrestricted."""
        listed: set[str] = set()
        if self.allowlist is not None:
            raw = config.get(self.allowlist.field)
            for entry in listed_entries(raw):
                if isinstance(entry, dict) and entry.get("enabled") is False:
                    continue
                listed.add(self.scope_key(self.allowlist.rule_key(entry)))
            listed.discard("")
            if not listed and self.allowlist.single_key_field and config.get(self.allowlist.single_key_field):
                listed.add(self.scope_key(config.get(self.allowlist.single_key_field)))
            if not listed and self.allowlist.serves_unlisted:
                return None
            return frozenset(listed)
        for name in self.default_key_fields:
            if str(config.get(name) or "").strip():
                listed.add(self.scope_key(config.get(name)))
        return frozenset(listed)

    def public(self) -> dict[str, Any]:
        """What the admin UI renders: binding, fields (secrets flagged), form kind, test and unscoped rule."""
        return {
            "connector_name": self.connector,
            "label": self.label,
            "binding": self.binding.public(),
            "fields": [item.public() for item in self.fields],
            "url_field": self.usable_field,
            "form": self.form,
            "testable": self.testable,
            "lists_visible_scopes": self.visible_scopes is not None,
            "unscoped": self.unscoped,
        }


def _set(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is True or (value not in (None, False, [], {}) and not isinstance(value, bool))


def present(config: dict, name: str) -> bool:
    """A field with a value (a stored secret counts by its ``*_secret_ref``)."""
    value = config.get(name)
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, [], {}) or bool(str(config.get(f"{name}_secret_ref") or "").strip())


def require_fields(config: dict, *names: str, code: str = "connection_invalid") -> None:
    """:class:`UnitIncompleteError` naming the first missing field."""
    for name in names:
        if not present(config, name):
            raise UnitIncompleteError(code, f"An own connection needs {name}.")


def listed_entries(raw: Any) -> list[Any]:
    """An allowlist value as a list: a list as is, a comma/space separated string split, nothing as ``[]``."""
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return list(raw)
    return [item for item in str(raw).replace(",", " ").split() if item]


__all__ = [
    "CASE_EXACT",
    "CASE_LOWER",
    "CASE_UPPER",
    "FIELD_KINDS",
    "FORM_FIELDS",
    "UNSCOPED_DEFAULT",
    "UNSCOPED_SINGLE",
    "Allowlist",
    "Binding",
    "ConnectorDescriptor",
    "Field",
    "UnitIncompleteError",
    "listed_entries",
    "present",
    "require_fields",
    "rule_key",
]
