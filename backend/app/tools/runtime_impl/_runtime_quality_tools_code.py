"""Quality tooling for linting, sast, and codebase analysis."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...services import code_quality_service
from ._runtime_cwd_resolution import _resolve_cwd


class LintAndFormatWorkspaceTool:
    name = "lint_and_format_workspace"
    description = "Run repository linting, formatting and optional SAST checks with structured results."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await _resolve_code_quality_service("lint_and_format_workspace")(
            cwd=cwd,
            auto_fix=bool(params.get("auto_fix", False)),
            include_sast=bool(params.get("include_sast", True)),
            timeout_sec=int(params.get("timeout_sec") or 120),
            project_config=context.project_config,
            db=context.db,
        )


class RunSastSuiteTool:
    name = "run_sast_suite"
    description = "Run repository security scanning with language-aware SAST runners and structured results."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        raw_runners = params.get("runners")
        runners = (
            [str(item).strip() for item in raw_runners if str(item).strip()] if isinstance(raw_runners, list) else None
        )
        return await _resolve_code_quality_service("run_sast_suite")(
            cwd=cwd,
            timeout_sec=int(params.get("timeout_sec") or 120),
            runners=runners,
            project_config=context.project_config,
            db=context.db,
        )


class RunOpenRewriteRecipeTool:
    name = "run_openrewrite_recipe"
    description = "Run OpenRewrite recipes for a Java repository and return structured refactor results."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        raw_recipes = params.get("recipes")
        recipes = (
            [str(item).strip() for item in raw_recipes if str(item).strip()] if isinstance(raw_recipes, list) else None
        )
        raw_recipe_artifacts = params.get("recipe_artifacts")
        recipe_artifacts = (
            [str(item).strip() for item in raw_recipe_artifacts if str(item).strip()]
            if isinstance(raw_recipe_artifacts, list)
            else None
        )
        return await _resolve_code_quality_service("run_openrewrite_recipe")(
            cwd=cwd,
            recipes=recipes,
            recipe_artifacts=recipe_artifacts,
            dry_run=bool(params.get("dry_run", False)),
            timeout_sec=int(params.get("timeout_sec") or 300),
            export_datatables=bool(params.get("export_datatables", True)),
            project_config=context.project_config,
            db=context.db,
        )


class AnalyzeCodebasePatternsTool:
    name = "analyze_codebase_patterns"
    description = "Extract naming, import, error-handling and test conventions from the current repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        patterns = _resolve_code_quality_service("analyze_codebase_patterns")(
            cwd=cwd,
            max_files=max(1, min(int(params.get("max_files") or 20), 50)),
        )
        # The conventions are returned to the caller only; nothing is persisted.
        return {"persisted": False, **patterns}


class GetRepoCodeQualityConfigTool:
    name = "get_repo_code_quality_config"
    description = "Detect or read repo-specific code-quality settings for tests, linting and formatting."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return _resolve_code_quality_service("load_repo_code_quality_config")(
            cwd, project_config=context.project_config
        )


_CODE_QUALITY_SERVICES = frozenset({
    "analyze_codebase_patterns",
    "lint_and_format_workspace",
    "load_repo_code_quality_config",
    "run_openrewrite_recipe",
    "run_sast_suite",
})


def _resolve_code_quality_service(function_name: str):
    """The code-quality function ``function_name``, read from its defining module at call time."""
    if function_name not in _CODE_QUALITY_SERVICES:
        raise KeyError(function_name)
    return getattr(code_quality_service, function_name)


__all__ = [
    "LintAndFormatWorkspaceTool",
    "RunSastSuiteTool",
    "RunOpenRewriteRecipeTool",
    "AnalyzeCodebasePatternsTool",
    "GetRepoCodeQualityConfigTool",
]
