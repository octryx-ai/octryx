"""Connector-owned credential resolution helpers."""

from __future__ import annotations

from ...services.secret import get_secret_value, secret_ref_field_name
from ..context import ToolContext
from .common import _string


async def connector_secret_value(context: ToolContext, *, connector_name: str, field_name: str) -> str:
    config = context.project_config or {}
    raw_value = _string(config.get(field_name))
    if raw_value:
        return raw_value

    secret_ref = _string(config.get(secret_ref_field_name(field_name)))
    if not secret_ref or context.db is None:
        return ""
    value = await get_secret_value(
        context.db,
        secret_id=secret_ref,
        expected_tool_name=connector_name,
        expected_field_name=field_name,
        expected_project_id=None,
        purpose="connector.tool_call",
    )
    return _string(value)


