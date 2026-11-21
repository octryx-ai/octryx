"""Validation and normalization of an agent's reply contract.

The contract rules are described in :mod:`app.services.agent_reply_contract`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .agent_reply_contract_model import NamedSchema

REPLY_CONTRACT_FIELD = "reply_contract"
REPLY_CONTRACT_PAYLOAD_KEY = "replyContract"

KIND_TEXT = "text"
KIND_JSON_OBJECT = "json_object"
PRIMITIVE_TYPES = ("string", "integer", "number", "boolean")
MAX_FIELDS = 32
MAX_CONTRACT_BYTES = 16 * 1024
# The ``FieldName`` rule of ``agent_reply_contract_model``, applied before the model parses.
_FIELD_NAME = re.compile(r"^[a-z][A-Za-z0-9_]{0,63}$")

REASON_CONTRACT_INVALID = "agent_reply_contract_invalid"
REASON_NOT_JSON = "agent_reply_not_json"
REASON_SCHEMA_MISMATCH = "agent_reply_schema_mismatch"
STATUS_SATISFIED = "satisfied"
STATUS_VIOLATED = "violated"

_SCHEMA_NAME = "Reply"


class ReplyContractError(ValueError):
    """An invalid contract; the message is fixed plain English and never echoes the input."""

    code = REASON_CONTRACT_INVALID

    def __init__(self, message: str = "The reply format is not a valid reply contract.") -> None:
        super().__init__(message)


def text_contract() -> dict[str, str]:
    return {"kind": KIND_TEXT}


def _bounded_size(value: Any) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReplyContractError() from exc
    if size > MAX_CONTRACT_BYTES:
        raise ReplyContractError("The reply format exceeds its 16 KiB size limit.")


def _field(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
        raise ReplyContractError("Each reply field needs a type.")
    kind = spec["type"]
    if kind in PRIMITIVE_TYPES:
        if set(spec) != {"type"}:
            raise ReplyContractError("A reply field allows only its type.")
        return {"type": kind}
    items = spec.get("items")
    if kind != "array" or set(spec) != {"type", "items"} or not isinstance(items, dict) or set(items) != {"type"}:
        raise ReplyContractError("Reply fields are text, whole numbers, numbers, true/false or lists of one of them.")
    if items["type"] not in PRIMITIVE_TYPES:
        raise ReplyContractError("A list field holds text, whole numbers, numbers or true/false values.")
    return {"type": "array", "items": {"type": items["type"]}}


def normalize_reply_contract(value: Any) -> dict[str, Any]:
    """The canonical contract for *value*, or :class:`ReplyContractError` (nothing is coerced)."""
    if not isinstance(value, dict):
        raise ReplyContractError()
    _bounded_size(value)
    kind = value.get("kind")
    if kind == KIND_TEXT and set(value) == {"kind"}:
        return text_contract()
    if kind != KIND_JSON_OBJECT or set(value) != {"kind", "schema"}:
        raise ReplyContractError()
    schema = value["schema"]
    if (not isinstance(schema, dict) or set(schema) - {"type", "properties", "required"}
            or schema.get("type") != "object"):
        raise ReplyContractError("A checked reply is one object with declared fields and nothing else.")
    properties, required = schema.get("properties"), schema.get("required", [])
    if not isinstance(properties, dict) or not 1 <= len(properties) <= MAX_FIELDS:
        raise ReplyContractError("A checked reply declares 1 to 32 fields.")
    if not all(isinstance(name, str) and _FIELD_NAME.match(name) for name in properties):
        raise ReplyContractError("Field names start with a lowercase letter and use letters, digits or _ (max 64).")
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        raise ReplyContractError("Required fields are a list of declared field names.")
    if len(set(required)) != len(required) or set(required) - set(properties):
        raise ReplyContractError("Required fields must be declared once.")
    canonical = {
        "kind": KIND_JSON_OBJECT,
        "schema": {
            "type": "object",
            "properties": {name: _field(spec) for name, spec in properties.items()},
            "required": list(required),
        },
    }
    _named_schema(canonical)
    return canonical


def _named_schema(contract: Mapping[str, Any]) -> NamedSchema:
    """The IR model of a normalized contract; a contract the IR refuses is invalid too."""
    try:
        return NamedSchema.model_validate(contract["schema"])
    except ValueError as exc:
        raise ReplyContractError() from exc
