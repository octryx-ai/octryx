"""Code intelligence tools (status, index, search, symbols, outline) and the git tool aliases."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.workflow_runs.phase_workspace import code_index_repository_id
from ._runtime_cli_helpers import _with_code_intelligence_provenance
from ._runtime_code_intelligence_execution import _execute_outline_code_intelligence, _execute_symbol_code_intelligence
from ._runtime_code_service_resolvers import resolve_code_intelligence_service
from ._runtime_cwd_resolution import _resolve_cwd


class CodeIntelligenceStatusTool:
    name = "code_intelligence_status"
    description = "Show which repository code-intelligence backends are currently available in this runtime."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return _with_code_intelligence_provenance(
            {
                "workspace_root": context.workspace_root,
                "project_ids": context.project_ids,
                "capabilities": resolve_code_intelligence_service("detect_code_intelligence_capabilities")(),
            }
        )


class CodeIndexRepositoryTool:
    name = "code_index_repository"
    description = (
        "Build or refresh the persistent repository code-intelligence index for the current project repository."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        repository_id = str(params.get("repository_id") or "").strip()
        if not repository_id:
            return {"error": "repository_id is required"}
        if context.db is None:
            return {"error": "database session is required"}
        try:
            result = await resolve_code_intelligence_service("run_code_index")(
                context.db,
                repository_id=repository_id,
                force=bool(params.get("force", False)),
                trigger="tool",
            )
            return _with_code_intelligence_provenance(result)
        except HTTPException as exc:
            return {"error": exc.detail}
        except Exception as exc:
            return {"error": str(exc)}


class CodeSearchRepositoryTool:
    name = "code_search"
    description = "Search within the current repository using the persistent code-intelligence index and text fallback."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = str(params.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}
        try:
            cwd = _resolve_cwd(
                context.workspace_root,
                params.get("cwd"),
                context=context,
                allow_repo_fallback=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        result = await resolve_code_intelligence_service("search_repository_code")(
            db=context.db,
            # Inside a run phase the working copy, never a stored index at another commit.
            repository_id=code_index_repository_id(params, context.project_config),
            cwd=cwd,
            project_id=context.project_ids[0] if context.project_ids else None,
            query=query,
            limit=max(1, min(int(params.get("limit") or 20), 100)),
        )
        return _with_code_intelligence_provenance(result)


class CodeSymbolDefinitionTool:
    name = "code_symbol_definition"
    description = "Resolve likely definitions for a symbol inside the current repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_symbol_code_intelligence(
            service_name="find_symbol_definition",
            params=params,
            context=context,
        )


class CodeReferencesTool:
    name = "code_references"
    description = "Find references for a symbol in the current repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_symbol_code_intelligence(
            service_name="find_symbol_references",
            params=params,
            context=context,
            default_limit=50,
        )


class CodeCallersTool:
    name = "code_callers"
    description = "Find likely call sites for a function or method inside the current repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_symbol_code_intelligence(
            service_name="find_symbol_callers",
            params=params,
            context=context,
            default_limit=50,
        )


class CodeImpactAnalysisTool:
    name = "code_impact_analysis"
    description = "Estimate impacted files, related symbols and review scope for a repository symbol."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_symbol_code_intelligence(
            service_name="build_impact_analysis",
            params=params,
            context=context,
            default_limit=50,
        )


class CodeFileOutlineTool:
    name = "code_file_outline"
    description = "Return the structural outline and code chunks for a repository file."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_outline_code_intelligence(params, context)



__all__ = [name for name in vars() if not name.startswith("_")]
