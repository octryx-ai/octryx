from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.database_tool.common import (
    DATABASE_TOOL_PREFIX,
    normalize_parameter_schema,
    normalize_rls_rules,
    tool_visible_to_context,
)
from app.services.database_tool.query_runs import (
    classify_database_query_exception,
    complete_database_query_tool_run,
    create_database_query_tool_run,
    fail_database_query_tool_run,
    query_run_result_metadata,
    sanitize_database_query_tool_error,
)
from app.services.database_tool.runtime_policy import database_runtime_profile
from app.services.error_facts import error_text

from ...models import DatabaseConnector, DatabaseQueryTool
from ...tools.context import ToolContext
from .connector_engine import get_connector_engine, resolve_connector_config
from .parameters import (
    DatabaseToolParameterError,
    build_rls_context_values,
    compile_rls_rules,
    validate_call_params,
)


async def run_database_query_tool(
    db: AsyncSession,
    *,
    tool: DatabaseQueryTool,
    params: dict[str, Any],
    context: ToolContext,
    secret_scope: str,
) -> dict[str, Any]:
    schema = normalize_parameter_schema(tool.parameters_schema, strict=True)
    normalized_params = validate_call_params(schema, params)
    resolved_config = await resolve_connector_config(db, connector=tool.connector, secret_scope=secret_scope)
    engine = await get_connector_engine(tool.connector, resolved_config)
    rls_values = await build_rls_context_values(db, context)
    rls_clause, rls_bindings = compile_rls_rules(
        normalize_rls_rules(tool.row_level_security_rules, strict=True),
        rls_values,
    )

    statement_sql = f"SELECT * FROM ({tool.sql_template}) AS managed_query"
    if rls_clause:
        statement_sql += f" WHERE {rls_clause}"
    statement_sql += " LIMIT :__managed_limit"
    stmt = text(statement_sql)
    for binding in rls_bindings:
        stmt = stmt.bindparams(binding)
    for key, value in normalized_params.items():
        if isinstance(value, list):
            stmt = stmt.bindparams(bindparam(key, value=value, expanding=True))
        else:
            stmt = stmt.bindparams(bindparam(key, value=value))
    stmt = stmt.bindparams(bindparam("__managed_limit", value=max(1, min(int(tool.max_rows or 100), 10000))))

    async with engine.connect() as conn:
        result = await asyncio.wait_for(conn.execute(stmt), timeout=max(1, int(tool.timeout_seconds or 30)))
        rows = [dict(row) for row in result.mappings().all()]
    return {
        "tool_name": tool.tool_name,
        "connector_name": tool.connector.name,
        "db_type": tool.connector.db_type,
        "runtime_profile": database_runtime_profile(tool.connector.db_type),
        "row_count": len(rows),
        "max_rows": int(tool.max_rows or 100),
        "rows": rows,
        "applied_rls_rules": normalize_rls_rules(tool.row_level_security_rules),
    }


async def _active_tool(db: AsyncSession, tool_name: str) -> DatabaseQueryTool | None:
    result = await db.execute(
        select(DatabaseQueryTool)
        .options(selectinload(DatabaseQueryTool.connector))
        .join(DatabaseConnector)
        .where(
            DatabaseQueryTool.tool_name == tool_name,
            DatabaseQueryTool.is_active.is_(True),
            DatabaseConnector.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _validation_failure(db: AsyncSession, query_run, exc: Exception) -> dict[str, Any]:
    # Both carry messages authored in this package (connector URL and parameter/RLS checks).
    detail = getattr(exc, "detail", None) or str(exc)
    await fail_database_query_tool_run(
        db,
        run=query_run,
        message=detail,
        category="validation_failed",
        retryable=False,
    )
    return {
        "error": f"Database tool validation failed: {sanitize_database_query_tool_error(detail)}",
        "query_run": query_run_result_metadata(query_run),
    }


async def _execution_failure(db: AsyncSession, query_run, exc: Exception) -> dict[str, Any]:
    # Driver, engine and secret-resolution errors can carry DSNs, hosts and credentials:
    # the run record and the tool result keep only the fixed facts.
    category, retryable = classify_database_query_exception(exc)
    failure = error_text("database_tool_execution_failed", exc)
    await fail_database_query_tool_run(
        db, run=query_run, message=failure, category=category, retryable=retryable
    )
    return {
        "error": f"Database tool execution failed. {failure}",
        "query_run": query_run_result_metadata(query_run),
    }


async def execute_database_query_tool(
    db: AsyncSession,
    *,
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any]:
    if not tool_name.startswith(DATABASE_TOOL_PREFIX):
        return {"error": f"Unknown database tool: {tool_name}"}
    tool = await _active_tool(db, tool_name)
    if tool is None:
        return {"error": f"Unknown database tool: {tool_name}"}
    if not tool_visible_to_context(tool, context):
        return {"error": f"Tool '{tool_name}' is not available for the current user context"}
    applied_rls_rules = normalize_rls_rules(tool.row_level_security_rules)
    query_run = await create_database_query_tool_run(
        db,
        tool=tool,
        context=context,
        params=params or {},
        applied_rls_rules=applied_rls_rules,
    )
    try:
        result = await run_database_query_tool(
            db,
            tool=tool,
            params=params or {},
            context=context,
            secret_scope=f"database_connector:{tool.connector.id}",
        )
        await complete_database_query_tool_run(db, run=query_run, rows=list(result.get("rows") or []))
        result["query_run"] = query_run_result_metadata(query_run)
        return result
    except (HTTPException, DatabaseToolParameterError) as exc:
        return await _validation_failure(db, query_run, exc)
    except Exception as exc:
        return await _execution_failure(db, query_run, exc)
