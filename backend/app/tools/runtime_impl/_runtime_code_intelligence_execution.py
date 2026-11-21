"""Shared execution helpers for runtime code-intelligence tools."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.workflow_runs.phase_workspace import code_index_repository_id
from ._runtime_cli_helpers import _with_code_intelligence_provenance
from ._runtime_code_graph_guidance import _with_graph_agent_guidance
from ._runtime_code_service_resolvers import resolve_code_intelligence_service
from ._runtime_cwd_resolution import _resolve_cwd


def _build_code_intelligence_scope(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    cwd = _resolve_cwd(
        context.workspace_root,
        params.get("cwd"),
        context=context,
        allow_repo_fallback=True,
    )
    return {
        "db": context.db,
        "repository_id": code_index_repository_id(params, context.project_config),
        "cwd": cwd,
        "project_id": context.project_ids[0] if context.project_ids else None,
    }


def _bounded_limit(params: dict[str, Any], *, default: int, maximum: int) -> int:
    return _bounded_int(params, key="limit", default=default, maximum=maximum)


def _bounded_int(params: dict[str, Any], *, key: str, default: int, maximum: int) -> int:
    return max(1, min(int(params.get(key) or default), maximum))


async def _execute_symbol_code_intelligence(
    *,
    service_name: str,
    params: dict[str, Any],
    context: ToolContext,
    default_limit: int | None = None,
    maximum_limit: int = 200,
) -> dict[str, Any]:
    symbol = str(params.get("symbol") or "").strip()
    if not symbol:
        return {"error": "symbol is required"}
    try:
        scope = _build_code_intelligence_scope(params, context)
    except ValueError as exc:
        return {"error": str(exc)}

    request: dict[str, Any] = {**scope, "symbol": symbol}
    if default_limit is not None:
        request["limit"] = _bounded_limit(params, default=default_limit, maximum=maximum_limit)

    result = await resolve_code_intelligence_service(service_name)(**request)
    return _with_code_intelligence_provenance(result)


async def _execute_outline_code_intelligence(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    file_path = str(params.get("file_path") or params.get("path") or "").strip()
    if not file_path:
        return {"error": "file_path is required"}
    try:
        scope = _build_code_intelligence_scope(params, context)
    except ValueError as exc:
        return {"error": str(exc)}

    try:
        result = await resolve_code_intelligence_service("get_file_outline")(
            **scope,
            file_path=file_path,
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    return _with_code_intelligence_provenance(result)


async def _execute_graph_code_intelligence(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
    except ValueError as exc:
        return {"error": str(exc)}

    result = await resolve_code_intelligence_service("get_graph_summary")(**scope)
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_node(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_node")(
            **scope,
            node_id=str(params.get("node_id") or params.get("id") or "").strip() or None,
            query=str(params.get("query") or "").strip() or None,
            name=str(params.get("name") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            limit=_bounded_limit(params, default=10, maximum=50),
            include_source=bool(params.get("include_source")),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_neighbors(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_neighbors")(
            **scope,
            node_id=str(params.get("node_id") or params.get("id") or "").strip() or None,
            query=str(params.get("query") or "").strip() or None,
            name=str(params.get("name") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            relation=str(params.get("relation") or "").strip() or None,
            direction=str(params.get("direction") or "both"),
            depth=_bounded_int(params, key="depth", default=1, maximum=6),
            max_nodes=_bounded_int(params, key="max_nodes", default=25, maximum=50),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_trace(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    source = str(params.get("source") or params.get("from") or "").strip()
    target = str(params.get("target") or params.get("to") or "").strip()
    if not source or not target:
        return {"error": "source and target are required"}
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_trace")(
            **scope,
            source=source,
            target=target,
            direction=str(params.get("direction") or "both"),
            max_depth=_bounded_int(params, key="max_depth", default=6, maximum=6),
            include_source=bool(params.get("include_source")),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_stats(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_stats")(
            **scope,
            limit=_bounded_limit(params, default=10, maximum=50),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_status(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_status")(**scope)
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_god_nodes(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_god_nodes")(
            **scope,
            relation=str(params.get("relation") or "").strip() or None,
            node_type=str(params.get("node_type") or "").strip() or None,
            limit=_bounded_limit(params, default=10, maximum=50),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_affected(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_affected")(
            **scope,
            node_id=str(params.get("node_id") or params.get("id") or "").strip() or None,
            query=str(params.get("query") or "").strip() or None,
            name=str(params.get("name") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            relation=str(params.get("relation") or "").strip() or None,
            direction=str(params.get("direction") or "incoming"),
            depth=_bounded_int(params, key="depth", default=2, maximum=6),
            max_nodes=_bounded_int(params, key="max_nodes", default=50, maximum=50),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_callees(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_callees")(
            **scope,
            node_id=str(params.get("node_id") or params.get("id") or "").strip() or None,
            query=str(params.get("query") or "").strip() or None,
            name=str(params.get("name") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            limit=_bounded_limit(params, default=25, maximum=50),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_files(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_files")(
            **scope,
            language=str(params.get("language") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            limit=_bounded_limit(params, default=100, maximum=500),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_context(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    try:
        scope = _build_code_intelligence_scope(params, context)
        result = await resolve_code_intelligence_service("get_code_graph_context")(
            **scope,
            node_id=str(params.get("node_id") or params.get("id") or "").strip() or None,
            query=str(params.get("query") or "").strip() or None,
            name=str(params.get("name") or "").strip() or None,
            path=str(params.get("path") or "").strip() or None,
            relation=str(params.get("relation") or "").strip() or None,
            direction=str(params.get("direction") or "both"),
            depth=_bounded_int(params, key="depth", default=2, maximum=6),
            max_nodes=_bounded_int(params, key="max_nodes", default=50, maximum=50),
            budget_chars=_bounded_int(params, key="budget_chars", default=6000, maximum=20000),
        )
    except HTTPException as exc:
        return {"error": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}
    return _with_graph_agent_guidance(result)


async def _execute_code_graph_explore(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    result = await _execute_code_graph_context(
        {
            **params,
            "direction": str(params.get("direction") or "both"),
            "depth": _bounded_int(params, key="depth", default=2, maximum=4),
            "max_nodes": _bounded_int(params, key="max_nodes", default=25, maximum=40),
            "budget_chars": _bounded_int(params, key="budget_chars", default=4000, maximum=12000),
        },
        context,
    )
    if "error" in result:
        return result
    guidance = result.get("agent_guidance") if isinstance(result.get("agent_guidance"), list) else []
    result["agent_guidance"] = [
        "Use this compact graph exploration before broad file scanning; expand with code_context or code_trace only when needed.",
        *guidance,
    ]
    result["explore_mode"] = "compact_graph_context"
    result["source_files"] = result.get("context_files") if isinstance(result.get("context_files"), list) else []
    return result
