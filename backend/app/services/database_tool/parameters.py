"""Call parameters and row-level security of a database query tool: validation and the compiled RLS clause."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database_tool.common import RLS_TOKEN_RE

from ...models import IdentityGroup, Team, TeamMember, User, UserGroup
from ...tools.context import ToolContext


class DatabaseToolParameterError(ValueError):
    pass


def _value_matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    enum_values = schema.get("enum") if isinstance(schema.get("enum"), list) else []
    if enum_values and value not in enum_values:
        return False
    expected_type = str(schema.get("type") or "string").strip().lower()
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected_type == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {"type": "string"}
        return all(_value_matches_schema(item, item_schema) for item in value)
    return False


def validate_call_params(schema: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema.get("properties") or {})
    required = [str(item) for item in schema.get("required") or []]
    if not isinstance(params, dict):
        raise DatabaseToolParameterError("Database tool parameters must be an object")
    unknown = sorted(str(key) for key in params if key not in properties)
    if unknown:
        raise DatabaseToolParameterError(f"Unknown parameters: {', '.join(unknown)}")
    normalized = {key: value for key, value in dict(params or {}).items() if key in properties}
    missing = [name for name in required if normalized.get(name) in (None, "")]
    if missing:
        raise DatabaseToolParameterError(f"Missing required parameters: {', '.join(missing)}")
    invalid_types = [name for name, value in normalized.items() if not _value_matches_schema(value, properties[name])]
    if invalid_types:
        raise DatabaseToolParameterError(f"Invalid parameter types: {', '.join(sorted(invalid_types))}")
    return normalized


async def build_rls_context_values(db: AsyncSession, context: ToolContext) -> dict[str, Any]:
    user = await db.get(User, context.user_id)
    if user is None:
        raise DatabaseToolParameterError("RLS context user was not found")
    group_rows = (
        (
            await db.execute(
                select(Team.name)
                .join(TeamMember, TeamMember.team_id == Team.id)
                .where(TeamMember.user_id == context.user_id)
                .order_by(Team.name.asc())
            )
        )
        .scalars()
        .all()
    )
    identity_groups = (
        (
            await db.execute(
                select(IdentityGroup)
                .join(UserGroup, UserGroup.group_id == IdentityGroup.id)
                .where(UserGroup.user_id == context.user_id, IdentityGroup.is_active.is_(True))
                .order_by(IdentityGroup.name.asc())
            )
        )
        .scalars()
        .all()
    )
    rls_attribute_values: dict[str, list[str]] = {}
    for group in identity_groups:
        for attribute in group.rls_attributes_json or []:
            if not isinstance(attribute, dict):
                continue
            key = str(attribute.get("key") or "").strip()
            value = str(attribute.get("value") or "").strip()
            if not key or not value:
                continue
            token_name = f"group.rls.{key}"
            rls_attribute_values.setdefault(token_name, [])
            if value not in rls_attribute_values[token_name]:
                rls_attribute_values[token_name].append(value)
    rls_tokens: dict[str, Any] = {}
    for key, values in rls_attribute_values.items():
        rls_tokens[key] = values[0] if len(values) == 1 else values
    return {
        "user.id": context.user_id,
        "user.username": getattr(user, "username", None),
        "user.email": getattr(user, "email", None),
        "roles": list(context.roles or []),
        "groups": list(group_rows or []),
        "identity_groups": [group.name for group in identity_groups],
        "project_ids": list(context.project_ids or []),
        "session.id": context.session_id,
        **rls_tokens,
    }


def compile_rls_rules(rules: list[str], values: dict[str, Any]) -> tuple[str, list[Any]]:
    bind_params = []
    rendered_rules: list[str] = []
    bind_index = 0

    def replace_token(match) -> str:
        nonlocal bind_index
        token_name = str(match.group(1) or "")
        if token_name not in values:
            raise DatabaseToolParameterError(f"Unsupported RLS token ${token_name}")
        if values[token_name] in (None, ""):
            raise DatabaseToolParameterError(f"RLS context token ${token_name} has no value")
        bind_name = f"__rls_{bind_index}"
        bind_index += 1
        value = values[token_name]
        if isinstance(value, list):
            if not value:
                raise DatabaseToolParameterError(f"RLS context token ${token_name} has no values")
            bind_params.append(bindparam(bind_name, value=value, expanding=True))
        else:
            bind_params.append(bindparam(bind_name, value=value))
        return f":{bind_name}"

    for raw_rule in rules:
        rendered = RLS_TOKEN_RE.sub(replace_token, raw_rule.strip())
        if rendered:
            rendered_rules.append(f"({rendered})")
    return " AND ".join(rendered_rules), bind_params
