from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from ...models import DatabaseConnector, DatabaseQueryTool
from ...tools.context import ToolContext
from .runtime_policy import database_runtime_profile

DATABASE_TOOL_PREFIX = "database_tool_"
READ_ONLY_QUERY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
FORBIDDEN_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|merge|grant|revoke|call|exec|execute|attach|detach|pragma)\b",
    re.IGNORECASE,
)
RLS_TOKEN_RE = re.compile(r"\$([A-Za-z0-9_.]+)")
SQL_NAMED_PARAMETER_RE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
RLS_RULE_RE = re.compile(
    r"^\s*(?P<column>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s+"
    r"(?P<operator>=|!=|<>|in|not\s+in)\s+\$(?P<token>[A-Za-z0-9_.]+)\s*$",
    re.IGNORECASE,
)
RLS_SCALAR_TOKENS = {"session.id", "user.email", "user.id", "user.username"}
RLS_COLLECTION_TOKENS = {"groups", "identity_groups", "project_ids", "roles"}
RLS_GROUP_ATTRIBUTE_PREFIX = "group.rls."
SUPPORTED_PARAMETER_TYPES = {"array", "boolean", "integer", "number", "string"}
SUPPORTED_ARRAY_ITEM_TYPES = {"boolean", "integer", "number", "string"}
SAFE_PARAMETER_SCHEMA_KEYS = {
    "description",
    "enum",
    "format",
    "items",
    "maximum",
    "maxItems",
    "maxLength",
    "minimum",
    "minItems",
    "minLength",
    "pattern",
    "title",
    "type",
}
SECRET_FIELDS = {"dsn", "password"}
PUBLIC_DB_FIELDS = {
    "host",
    "port",
    "database",
    "username",
    "driver",
    "dsn",
    "ssl",
    "query_options",
    "file_path",
}


def secret_scope(connector_id: str) -> str:
    return f"database_connector:{connector_id}"


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _raise_or_skip(strict: bool, detail: str) -> None:
    if strict:
        raise HTTPException(status_code=400, detail=detail)


def _normalize_parameter_property(name: str, raw: Any, *, strict: bool) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        _raise_or_skip(strict, f"Invalid parameter name: {name}")
        return None
    if not isinstance(raw, dict):
        _raise_or_skip(strict, f"Parameter '{name}' schema must be an object")
        return None
    property_type = str(raw.get("type") or "string").strip().lower()
    if property_type not in SUPPORTED_PARAMETER_TYPES:
        _raise_or_skip(strict, f"Parameter '{name}' uses unsupported type: {property_type}")
        return None
    normalized = {key: value for key, value in raw.items() if key in SAFE_PARAMETER_SCHEMA_KEYS}
    normalized["type"] = property_type
    if property_type == "array":
        items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
        item_type = str(items.get("type") or "string").strip().lower()
        if item_type not in SUPPORTED_ARRAY_ITEM_TYPES:
            _raise_or_skip(strict, f"Parameter '{name}' array item type is unsupported: {item_type}")
            return None
        normalized["items"] = {"type": item_type}
        if "enum" in items:
            normalized["items"]["enum"] = list(items.get("enum") or [])
    else:
        normalized.pop("items", None)
    if "enum" in normalized:
        normalized["enum"] = list(normalized.get("enum") or [])
    return normalized


def normalize_parameter_schema(raw: Any, *, strict: bool = False) -> dict[str, Any]:
    schema = dict(raw) if isinstance(raw, dict) else {}
    if schema.get("type", "object") != "object":
        _raise_or_skip(strict, "Database tool parameters_schema must be an object schema")
    raw_properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    properties: dict[str, Any] = {}
    for raw_name, raw_property in raw_properties.items():
        name = str(raw_name or "").strip()
        normalized_property = _normalize_parameter_property(name, raw_property, strict=strict)
        if normalized_property is not None:
            properties[name] = normalized_property
    normalized_required = [item for item in normalize_string_list(schema.get("required")) if item in properties]
    if strict:
        unknown_required = [item for item in normalize_string_list(schema.get("required")) if item not in properties]
        if unknown_required:
            raise HTTPException(
                status_code=400,
                detail=f"Required parameters are not defined: {', '.join(sorted(unknown_required))}",
            )
    return {"type": "object", "properties": properties, "required": normalized_required, "additionalProperties": False}


def is_supported_rls_token(token_name: str) -> bool:
    normalized = str(token_name or "").strip()
    return (
        normalized in RLS_SCALAR_TOKENS
        or normalized in RLS_COLLECTION_TOKENS
        or normalized.startswith(RLS_GROUP_ATTRIBUTE_PREFIX)
    )


def validate_rls_rule(rule: str) -> str:
    normalized = str(rule or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="RLS rule must not be empty")
    if ";" in normalized or "--" in normalized or "/*" in normalized or "*/" in normalized:
        raise HTTPException(status_code=400, detail="RLS comments and multi-statement fragments are not allowed")
    if FORBIDDEN_SQL_RE.search(normalized):
        raise HTTPException(status_code=400, detail="RLS rule contains forbidden SQL keywords")
    match = RLS_RULE_RE.fullmatch(normalized)
    if match is None:
        raise HTTPException(status_code=400, detail="RLS rule must be '<column> <operator> $<supported_token>'")
    token_name = str(match.group("token") or "").strip()
    if not is_supported_rls_token(token_name):
        raise HTTPException(status_code=400, detail=f"Unsupported RLS token ${token_name}")
    return normalized


def normalize_rls_rules(raw: Any, *, strict: bool = False) -> list[str]:
    if isinstance(raw, str):
        values = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        values = []
    if strict:
        return [validate_rls_rule(value) for value in values]
    return values


def normalize_connector_config(raw: Any) -> dict[str, Any]:
    payload = dict(raw or {})
    config: dict[str, Any] = {}
    for field in PUBLIC_DB_FIELDS:
        if field in payload and payload[field] not in (None, ""):
            config[field] = payload[field]
    return config


def serialize_database_connector(connector: DatabaseConnector) -> dict[str, Any]:
    config = dict(connector.connection_config or {})
    public_fields = {
        key: value for key, value in config.items() if not key.endswith("_secret_ref") and key not in SECRET_FIELDS
    }
    secret_status = {field: bool(config.get(field) or config.get(f"{field}_secret_ref")) for field in SECRET_FIELDS}
    return {
        "id": connector.id,
        "project_id": connector.project_id,
        "name": connector.name,
        "description": connector.description or "",
        "db_type": connector.db_type,
        "is_active": connector.is_active,
        "runtime_profile": database_runtime_profile(connector.db_type),
        "public_fields": public_fields,
        "secret_status": secret_status,
        "tool_count": len(connector.query_tools or []),
        "created_at": connector.created_at.isoformat() if connector.created_at else None,
        "updated_at": connector.updated_at.isoformat() if connector.updated_at else None,
    }


def serialize_database_query_tool(tool: DatabaseQueryTool) -> dict[str, Any]:
    return {
        "id": tool.id,
        "connector_id": tool.connector_id,
        "project_id": tool.project_id,
        "tool_name": tool.tool_name,
        "display_name": tool.display_name or "",
        "description": tool.description or "",
        "sql_template": tool.sql_template,
        "parameters_schema": normalize_parameter_schema(tool.parameters_schema),
        "row_level_security_rules": normalize_rls_rules(tool.row_level_security_rules),
        "allowed_roles": normalize_string_list(tool.allowed_roles),
        "max_rows": int(tool.max_rows or 100),
        "timeout_seconds": int(tool.timeout_seconds or 30),
        "is_active": tool.is_active,
        "connector_name": tool.connector.name if tool.connector else None,
        "connector_type": tool.connector.db_type if tool.connector else None,
        "runtime_profile": database_runtime_profile(tool.connector.db_type if tool.connector else None),
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
    }


def validate_tool_name(tool_name: str) -> str:
    normalized = str(tool_name or "").strip()
    if not normalized.startswith(DATABASE_TOOL_PREFIX):
        raise HTTPException(status_code=400, detail="Database tools must start with database_tool_")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise HTTPException(status_code=400, detail="Tool name must be a valid identifier")
    return normalized


def sql_parameter_names(sql_template: str) -> set[str]:
    return set(SQL_NAMED_PARAMETER_RE.findall(str(sql_template or "")))


def validate_sql_template(sql_template: str, parameters_schema: dict[str, Any] | None = None) -> str:
    normalized = str(sql_template or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="SQL template is required")
    if ";" in normalized:
        raise HTTPException(status_code=400, detail="Only a single SELECT statement is allowed")
    if "--" in normalized or "/*" in normalized or "*/" in normalized:
        raise HTTPException(status_code=400, detail="SQL comments are not allowed in database query tools")
    if not READ_ONLY_QUERY_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Only SELECT/CTE queries are allowed")
    if FORBIDDEN_SQL_RE.search(normalized):
        raise HTTPException(status_code=400, detail="Query contains forbidden SQL keywords")
    declared_parameters = set((parameters_schema or {}).get("properties") or {})
    used_parameters = sql_parameter_names(normalized)
    reserved_parameters = {name for name in used_parameters if name.startswith("__")}
    if reserved_parameters:
        raise HTTPException(
            status_code=400,
            detail=f"SQL template uses reserved parameters: {', '.join(sorted(reserved_parameters))}",
        )
    undeclared_parameters = sorted(used_parameters - declared_parameters)
    if undeclared_parameters:
        raise HTTPException(
            status_code=400,
            detail=f"SQL template uses undeclared parameters: {', '.join(undeclared_parameters)}",
        )
    return normalized


def tool_visible_to_context(tool: DatabaseQueryTool, context: ToolContext) -> bool:
    allowed_roles = {role.lower() for role in normalize_string_list(tool.allowed_roles)}
    if allowed_roles and not any(role.lower() in allowed_roles for role in (context.roles or [])):
        return False
    project_ids = set(context.project_ids or [])
    if tool.project_id and tool.project_id not in project_ids:
        return False
    connector_project_id = getattr(tool.connector, "project_id", None)
    if connector_project_id and connector_project_id not in project_ids:
        return False
    return True
