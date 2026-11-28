"""The connector descriptor: all one connector type contributes to named connections."""

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
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Field:
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
    if isinstance(entry, dict):
        return str(entry.get("space_key") or entry.get("key") or entry.get("table") or "").strip()
    return str(entry or "").strip()


def _key_entry(key: str) -> Any:
    return key


@dataclass(frozen=True, slots=True)
class Allowlist:
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
    value = config.get(name)
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, [], {}) or bool(str(config.get(f"{name}_secret_ref") or "").strip())


def require_fields(config: dict, *names: str, code: str = "connection_invalid") -> None:
    for name in names:
        if not present(config, name):
            raise UnitIncompleteError(code, f"An own connection needs {name}.")


def listed_entries(raw: Any) -> list[Any]:
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
