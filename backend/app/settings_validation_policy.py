"""Input-free rendering of settings-validation failures, and the loader that applies it."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TypeVar, get_args

from pydantic import BaseModel, ValidationError
from pydantic.aliases import AliasChoices
from pydantic_settings import BaseSettings, SettingsError

SettingsT = TypeVar("SettingsT", bound=BaseSettings)

# A location part that the settings class does not declare, or that is not shaped
# like a name at all. Never the undeclared part itself.
REDACTED_LOCATION_PART = "?"
# Location for a failure that names no field: a model-level validator that did not
# name the settings it rejected, or a settings source that failed before any field.
UNNAMED_LOCATION = "settings"

FAILURE_HEADER = "Settings validation failed; no configuration value is included in this message."

_GENERIC_REASON = "invalid_value"
_GENERIC_REMEDIATION = "Set an accepted value for this setting in the process environment or .env."
_SOURCE_REASON = "settings_source_error"
_SOURCE_REMEDIATION = (
    "The configured value for this setting could not be read by its settings source. "
    "Provide it in the documented form in the process environment or .env."
)

# Reason codes are Pydantic's own error types; only the remediation is ours. Types
# without an entry fall back to the generic sentence, which keeps an unfamiliar
# Pydantic error informative about *where* without quoting anything.
_PYDANTIC_REMEDIATION: dict[str, str] = {
    "missing": "Provide this required setting in the process environment or .env.",
    "int_parsing": "Provide a plain integer, with no unit suffix, separator or quotes.",
    "int_type": "Provide a plain integer, with no unit suffix, separator or quotes.",
    "int_from_float": "Provide a whole number of units, not a fractional one.",
    "bool_parsing": "Provide a boolean: true or false.",
    "bool_type": "Provide a boolean: true or false.",
    "float_parsing": "Provide a decimal number, with no unit suffix or quotes.",
    "string_type": "Provide a plain string value.",
    "json_invalid": "Provide well-formed JSON for this setting.",
    "extra_forbidden": "This setting is not declared by the application; remove it.",
    "literal_error": "Provide one of the values this setting declares.",
    "value_error": "This setting's value is not accepted; see its declaration in app/config.py.",
    "assertion_error": "This setting's value is not accepted; see its declaration in app/config.py.",
}

# Both a reason code and a location part must look like a code, never like content.
_CODE_SHAPE = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_NAME_SHAPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
# pydantic-settings names the field, and only the field, in its own message.
_SOURCE_FIELD = re.compile(r'field "([^"]{1,64})"')


@dataclass(frozen=True, slots=True)
class SettingsFault:
    location: str
    reason: str
    remediation: str


class SettingsFieldError(ValueError):
    def __init__(self, reason: str, remediation: str, fields: Iterable[str] = ()) -> None:
        resolved = tuple(fields)
        named = f"{remediation} Affected settings: {', '.join(resolved)}." if resolved else remediation
        super().__init__(named)
        self.reason = reason
        self.remediation = remediation
        self.fields = resolved


class SettingsValidationError(RuntimeError):
    def __init__(self, faults: Iterable[SettingsFault]) -> None:
        resolved = tuple(faults) or (SettingsFault(UNNAMED_LOCATION, _GENERIC_REASON, _GENERIC_REMEDIATION),)
        super().__init__(render_settings_faults(resolved))
        self.faults = resolved
        self.safe_field_reasons = tuple((fault.location, fault.reason) for fault in resolved)


def render_settings_faults(faults: Iterable[SettingsFault]) -> str:
    grouped: dict[tuple[str, str], list[str]] = {}
    for fault in faults:
        grouped.setdefault((fault.reason, fault.remediation), []).append(fault.location)
    lines = [
        f"  - {', '.join(locations)} [{reason}] {remediation}"
        for (reason, remediation), locations in grouped.items()
    ]
    return "\n".join([FAILURE_HEADER, *lines])


def load_validated_settings(settings_cls: type[SettingsT]) -> SettingsT:
    faults: tuple[SettingsFault, ...] | None = None
    try:
        return settings_cls()
    except ValidationError as exc:
        faults = settings_validation_faults(exc, settings_cls)
    except SettingsError as exc:
        faults = settings_source_faults(exc, settings_cls)
    raise SettingsValidationError(faults)


def settings_validation_faults(
    exc: ValidationError, settings_cls: type[BaseSettings]
) -> tuple[SettingsFault, ...]:
    declared = declared_locations(settings_cls)
    faults: list[SettingsFault] = []
    for item in exc.errors(include_input=False, include_url=False):
        rejection = (item.get("ctx") or {}).get("error")
        if isinstance(rejection, SettingsFieldError):
            locations = tuple(_location_part(name, declared) for name in rejection.fields)
            faults.extend(
                SettingsFault(location, _reason(rejection.reason), rejection.remediation)
                for location in locations or (_location(item["loc"], declared),)
            )
            continue
        error_type = str(item["type"])
        faults.append(
            SettingsFault(
                _location(item["loc"], declared),
                _reason(error_type),
                _PYDANTIC_REMEDIATION.get(error_type, _GENERIC_REMEDIATION),
            )
        )
    return _deduplicated(faults)


def settings_source_faults(exc: SettingsError, settings_cls: type[BaseSettings]) -> tuple[SettingsFault, ...]:
    match = _SOURCE_FIELD.search(str(exc))
    name = match.group(1) if match else ""
    declared = declared_locations(settings_cls)
    location = _location_part(name, declared) if name in declared else UNNAMED_LOCATION
    return (SettingsFault(location, _SOURCE_REASON, _SOURCE_REMEDIATION),)


def declared_locations(model: type[BaseModel], _depth: int = 4) -> frozenset[str]:
    if _depth <= 0:
        return frozenset()
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        names.update(_field_aliases(field))
        for nested in _nested_models(field.annotation):
            names |= declared_locations(nested, _depth - 1)
    return frozenset(names)


def _field_aliases(field: object) -> Iterator[str]:
    for candidate in (getattr(field, "alias", None), getattr(field, "validation_alias", None)):
        if isinstance(candidate, str):
            yield candidate
        elif isinstance(candidate, AliasChoices):
            yield from (choice for choice in candidate.choices if isinstance(choice, str))


def _nested_models(annotation: object) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            yield annotation
        return
    for argument in get_args(annotation):
        yield from _nested_models(argument)


def _location(loc: tuple[object, ...], declared: frozenset[str]) -> str:
    parts = tuple(_location_part(part, declared) for part in loc)
    return ".".join(parts) if parts else UNNAMED_LOCATION


def _location_part(part: object, declared: frozenset[str]) -> str:
    # A list index is generated by the parser, not supplied as content.
    if isinstance(part, int):
        return str(part)
    if isinstance(part, str) and part in declared and _NAME_SHAPE.match(part):
        return part
    return REDACTED_LOCATION_PART


def _reason(code: str) -> str:
    return code if _CODE_SHAPE.match(code) else _GENERIC_REASON


def _deduplicated(faults: Iterable[SettingsFault]) -> tuple[SettingsFault, ...]:
    unique: dict[SettingsFault, None] = {}
    for fault in faults:
        unique.setdefault(fault, None)
    return tuple(unique)


__all__ = [
    "FAILURE_HEADER",
    "REDACTED_LOCATION_PART",
    "UNNAMED_LOCATION",
    "SettingsFault",
    "SettingsFieldError",
    "SettingsValidationError",
    "declared_locations",
    "load_validated_settings",
    "render_settings_faults",
    "settings_source_faults",
    "settings_validation_faults",
]
