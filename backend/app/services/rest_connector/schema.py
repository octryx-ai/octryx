"""The tool's parameter schema and the check of a call's arguments.

The model sees only what the operation declares: its path, query and header parameters (after the admin's
overlay) and, for a read-only POST, a ``body`` object. The base URL and host are never parameters, and the
parameters of the caller's data scope are not offered as free fields (``authorization.scope_schema``).
"""

from __future__ import annotations

from typing import Any

from .param_names import model_names

BODY_PARAM = "body"
CURSOR_PARAM = "cursor"
_SCHEMA_KEYS = frozenset({
    "type", "description", "enum", "format", "items", "properties", "required", "minimum", "maximum",
    "minLength", "maxLength", "minItems", "maxItems", "pattern", "default", "title", "nullable",
    "additionalProperties",
})
_PRIMITIVES = {"string", "integer", "number", "boolean", "array", "object"}


class ArgumentError(ValueError):
    """A call's arguments do not fit the declared parameters; the message is authored here and safe to return."""


def clean_schema(raw: Any, depth: int = 0) -> dict[str, Any]:
    """A JSON schema reduced to the keys a tool schema needs (nested ``properties`` and ``items`` included)."""
    if not isinstance(raw, dict) or depth > 12:
        return {"type": "object"} if depth > 12 else {"type": "string"}
    schema = {key: value for key, value in raw.items() if key in _SCHEMA_KEYS}
    kind = schema.get("type")
    if isinstance(kind, list):  # OpenAPI 3.1 ["string", "null"]
        kind = next((item for item in kind if item != "null"), "string")
    if kind not in _PRIMITIVES:
        kind = "object" if "properties" in schema else "string"
    schema["type"] = kind
    schema.pop("nullable", None)
    if isinstance(schema.get("properties"), dict):
        schema["properties"] = {
            str(name): clean_schema(value, depth + 1) for name, value in schema["properties"].items()
        }
    if kind == "array":
        schema["items"] = clean_schema(schema.get("items") or {"type": "string"}, depth + 1)
    else:
        schema.pop("items", None)
    if isinstance(schema.get("additionalProperties"), dict):
        schema["additionalProperties"] = clean_schema(schema["additionalProperties"], depth + 1)
    if "required" in schema and not isinstance(schema["required"], list):
        schema.pop("required")
    return schema


def declared_parameters(operation: Any) -> dict[str, dict[str, Any]]:
    """The operation's parameters by model name, with the admin overlay applied (description, hidden, fixed value).

    ``wire`` is the name the value is sent under (``$filter`` for the model's ``filter``, ``param_names``)."""
    overlay = dict(operation.params_overlay or {})
    raws = [raw for raw in operation.parameters or [] if isinstance(raw, dict) and raw.get("name")]
    names = model_names([str(raw["name"]) for raw in raws])
    declared: dict[str, dict[str, Any]] = {}
    for raw in raws:
        stored = str(raw["name"])
        name = names[stored]
        extra = overlay.get(name, overlay.get(stored))
        extra = extra if isinstance(extra, dict) else {}
        declared[name] = {
            "name": name,
            "wire": str(raw.get("wire_name") or stored),
            "explode": raw.get("explode") is not False,
            "in": str(raw.get("in") or "query"),
            "required": bool(raw.get("required")),
            "description": str(extra.get("description") or raw.get("description") or ""),
            "schema": clean_schema(raw.get("schema")),
            "hidden": bool(extra.get("hidden")),
            "fixed": extra.get("value") if "value" in extra else None,
        }
    return declared


def cursor_param_name(declared: dict[str, Any]) -> str:
    return CURSOR_PARAM if CURSOR_PARAM not in declared else "page_cursor"


def build_parameters_schema(
    operation: Any,
    *,
    scope_choices: dict[str, list[Any]] | None = None,
    paginated: bool = False,
) -> dict[str, Any]:
    """The JSON schema the model sees for this caller.

    ``scope_choices``: per scoped parameter, the values the caller's grants allow; one value is injected and hidden,
    several become an enum the model must choose from.
    """
    choices = scope_choices or {}
    declared = declared_parameters(operation)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in declared.items():
        if param["hidden"] or param["fixed"] is not None:
            continue
        allowed = choices.get(name)
        if allowed is not None and len(allowed) == 1:
            continue
        schema = dict(param["schema"])
        if param["description"]:
            schema["description"] = param["description"]
        if allowed:
            schema["enum"] = list(allowed)
            schema["description"] = (schema.get("description", "") + " Your access is limited to these values.").strip()
            required.append(name)
        elif param["required"]:
            required.append(name)
        properties[name] = schema
    body = operation.request_body if isinstance(operation.request_body, dict) else None
    if body:
        properties[BODY_PARAM] = clean_schema(body.get("schema") or {"type": "object"})
        if body.get("required"):
            required.append(BODY_PARAM)
    if paginated:
        properties[cursor_param_name(declared)] = {
            "type": "string",
            "description": "The next_cursor of the previous page; leave out for the first page.",
        }
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _fits(value: Any, schema: dict[str, Any]) -> bool:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in enum:
        return False
    kind = schema.get("type", "string")
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "array":
        items = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return isinstance(value, list) and all(_fits(item, items) for item in value)
    if kind == "object":
        return isinstance(value, dict)
    return True


def check_arguments(schema: dict[str, Any], arguments: Any) -> dict[str, Any]:
    """The arguments when they fit ``schema`` (no unknown name, every required one, the declared types)."""
    if not isinstance(arguments, dict):
        raise ArgumentError("The arguments must be an object.")
    properties = schema.get("properties") or {}
    unknown = sorted(name for name in arguments if name not in properties)
    if unknown:
        raise ArgumentError(f"Unknown parameters: {', '.join(unknown)}")
    missing = [name for name in schema.get("required") or [] if arguments.get(name) in (None, "")]
    if missing:
        raise ArgumentError(f"Missing required parameters: {', '.join(missing)}")
    wrong = sorted(
        name for name, value in arguments.items() if value is not None and not _fits(value, properties[name])
    )
    if wrong:
        raise ArgumentError(f"Invalid values for: {', '.join(wrong)}")
    return {name: value for name, value in arguments.items() if value is not None}


__all__ = [
    "BODY_PARAM",
    "CURSOR_PARAM",
    "ArgumentError",
    "build_parameters_schema",
    "check_arguments",
    "clean_schema",
    "cursor_param_name",
    "declared_parameters",
]
