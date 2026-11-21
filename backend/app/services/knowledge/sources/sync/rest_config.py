"""The configuration of a Custom REST Knowledge source (kind ``custom_rest``).

Validated and refused, never cleaned up. The admin API carries it as two generic objects, so a new kind needs no new
body fields (``scope`` and ``mapping``); both are stored together in the connector's ``scope`` column:

- ``scope``: ``definition`` (the REST API's key), ``operation`` (its list operation), ``role`` (the Octryx role whose
  grant and data scope the sync runs in, as for the Work intake: ``secure_work/custom_rest/listing.acting_role``),
  ``arguments`` (fixed arguments of the list call), ``detail_operation`` + ``detail_param`` (a read that returns one
  record's content, called with the record's id), ``updated_since_param`` (a list parameter that narrows the listing
  to records changed since an instant: it enables incremental scheduled runs), ``media_type`` and ``visibility``;
- ``mapping``: dotted record paths for ``id`` and ``title`` (required), ``url``, ``updated_at``, ``version`` and
  ``content``.

Why ``version`` or ``updated_at`` is required: the runner fetches an item only when its version marker changed. A
source without either would have to be fetched and hashed in full on every run, so it is refused at save
(``custom_rest_version_required``) instead of quietly costing a full re-read each time.

Why ``visibility`` defaults to ``restricted``: the API is read with a technical account and the grants decide who may
see its data. Synced knowledge follows the grants unless an admin explicitly says the whole
Workspace may read it (``workspace``).

Every refusal names a fixed code and the field (:class:`InvalidRestSourceError`); the objects are size-capped so a
stored configuration stays a configuration.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ....rest_connector.authorization import ROLE_RE

MAX_SCOPE_BYTES = 8192
MAX_MAPPING_BYTES = 2048
MAX_ARGUMENTS = 20
MAX_ARGUMENT_CHARS = 500
MAX_NAME_CHARS = 64

MEDIA_JSON = "application/json"
# Text-native: ingested in-process. HTML and PDF go through the parser sandbox (a PDF arrives base64 in a field).
MEDIA_TYPES = (MEDIA_JSON, "text/markdown", "text/plain", "text/html", "application/pdf")
SANDBOXED_MEDIA = frozenset({"text/html", "application/pdf"})
VISIBILITY_RESTRICTED = "restricted"
VISIBILITY_WORKSPACE = "workspace"

SCOPE_KEYS = frozenset({"definition", "operation", "role", "arguments", "detail_operation", "detail_param",
                        "updated_since_param", "media_type", "visibility"})
MAPPING_KEYS = frozenset({"id", "title", "url", "updated_at", "version", "content"})

_DEFINITION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NAME = re.compile(r"^[A-Za-z0-9_$@.:-]{1,120}$")
_PATH = re.compile(r"^[A-Za-z0-9_$@:-]+(\.[A-Za-z0-9_$@:-]+)*$")


class InvalidRestSourceError(ValueError):
    """A refused Custom REST source setting; ``code`` and ``field`` are fixed strings, never a value."""

    def __init__(self, code: str, field: str) -> None:
        super().__init__(code)
        self.code = code
        self.field = field


def _object(raw: object, field: str, cap: int) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise InvalidRestSourceError("custom_rest_object_required", field)
    try:
        size = len(json.dumps(raw, default=str))
    except (TypeError, ValueError):
        raise InvalidRestSourceError("custom_rest_object_required", field) from None
    if size > cap:
        raise InvalidRestSourceError("custom_rest_too_large", field)
    return raw


def _name(raw: object, field: str, *, required: bool, pattern: re.Pattern[str] = _NAME) -> str | None:
    if raw in (None, "") and not required:
        return None
    if type(raw) is not str or not pattern.fullmatch(raw.strip()):
        raise InvalidRestSourceError("custom_rest_invalid_name", field)
    return raw.strip()


def _scalar(value: object) -> bool:
    if isinstance(value, str):
        return len(value) <= MAX_ARGUMENT_CHARS and value.isprintable()
    return isinstance(value, int | float | bool)


def _arguments(raw: object) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping) or len(raw) > MAX_ARGUMENTS:
        raise InvalidRestSourceError("custom_rest_invalid_arguments", "scope.arguments")
    arguments: dict[str, Any] = {}
    for name, value in raw.items():
        values = value if isinstance(value, list) else [value]
        if type(name) is not str or len(name) > MAX_NAME_CHARS or len(values) > MAX_ARGUMENTS \
                or not all(_scalar(item) for item in values):
            raise InvalidRestSourceError("custom_rest_invalid_arguments", "scope.arguments")
        arguments[name] = value
    return arguments


def _choice(raw: object, choices: tuple[str, ...], default: str, field: str) -> str:
    if raw in (None, ""):
        return default
    if raw not in choices:
        raise InvalidRestSourceError("custom_rest_invalid_choice", field)
    return str(raw)


def _mapping(raw: object, media_type: str) -> dict[str, str]:
    given = _object(raw, "mapping", MAX_MAPPING_BYTES)
    if any(key not in MAPPING_KEYS for key in given):
        raise InvalidRestSourceError("custom_rest_unknown_field", "mapping")
    mapping: dict[str, str] = {}
    for name, path in given.items():
        if path in (None, ""):
            continue
        if type(path) is not str or not _PATH.fullmatch(path.strip()):
            raise InvalidRestSourceError("custom_rest_invalid_path", f"mapping.{name}")
        mapping[str(name)] = path.strip()
    for required in ("id", "title"):
        if required not in mapping:
            raise InvalidRestSourceError("custom_rest_field_required", f"mapping.{required}")
    if "version" not in mapping and "updated_at" not in mapping:
        raise InvalidRestSourceError("custom_rest_version_required", "mapping.updated_at")
    if media_type != MEDIA_JSON and "content" not in mapping:
        # Only JSON can be rendered from the whole record; any other type is one field's text (or base64 PDF).
        raise InvalidRestSourceError("custom_rest_field_required", "mapping.content")
    return mapping


def validate_rest_scope(scope: object, mapping: object) -> dict[str, Any]:
    """The stored ``scope`` of a ``custom_rest`` connector: the validated scope with its ``mapping`` inside."""
    given = _object(scope, "scope", MAX_SCOPE_BYTES)
    if any(key not in SCOPE_KEYS for key in given):
        raise InvalidRestSourceError("custom_rest_unknown_field", "scope")
    role = given.get("role")
    if role not in (None, "") and (type(role) is not str or not ROLE_RE.fullmatch(role.strip())):
        raise InvalidRestSourceError("custom_rest_invalid_name", "scope.role")
    media_type = _choice(given.get("media_type"), MEDIA_TYPES, MEDIA_JSON, "scope.media_type")
    validated: dict[str, Any] = {
        "definition": _name(given.get("definition"), "scope.definition", required=True, pattern=_DEFINITION),
        "operation": _name(given.get("operation"), "scope.operation", required=True),
        "role": role.strip() if isinstance(role, str) and role.strip() else None,
        "arguments": _arguments(given.get("arguments")),
        "detail_operation": _name(given.get("detail_operation"), "scope.detail_operation", required=False),
        "detail_param": _name(given.get("detail_param"), "scope.detail_param", required=False),
        "updated_since_param": _name(given.get("updated_since_param"), "scope.updated_since_param", required=False),
        "media_type": media_type,
        "visibility": _choice(given.get("visibility"), (VISIBILITY_RESTRICTED, VISIBILITY_WORKSPACE),
                              VISIBILITY_RESTRICTED, "scope.visibility"),
        "mapping": _mapping(mapping, media_type),
    }
    if validated["detail_param"] and not validated["detail_operation"]:
        raise InvalidRestSourceError("custom_rest_detail_operation_required", "scope.detail_param")
    return validated


__all__ = [
    "MEDIA_JSON",
    "MEDIA_TYPES",
    "SANDBOXED_MEDIA",
    "VISIBILITY_RESTRICTED",
    "VISIBILITY_WORKSPACE",
    "InvalidRestSourceError",
    "validate_rest_scope",
]
