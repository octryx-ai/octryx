"""Git and PR-oriented runtime tool wrappers."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ._runtime_code_service_resolvers import resolve_runtime_service
from ._runtime_cwd_resolution import _resolve_cwd


class GitFileIntelligenceTool:
    name = "git_file_intelligence"
    description = "Return compressed git history, ownership and co-change signals for a single file."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file") or "").strip()
        if not file_path:
            return {"error": "file is required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await resolve_runtime_service("git_file_intelligence")(
            cwd=cwd,
            file_path=file_path,
            days=max(1, min(int(params.get("days") or 90), 365)),
            db=context.db,
            project_config=context.project_config,
        )


class GitCouplingMapTool:
    name = "git_coupling_map"
    description = "Analyze which files usually change together, to detect incomplete code changes before commit."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        changed_files = params.get("changed_files") or []
        if not isinstance(changed_files, list) or not changed_files:
            return {"error": "changed_files is required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await resolve_runtime_service("git_coupling_map")(
            cwd=cwd,
            changed_files=[str(item) for item in changed_files if str(item).strip()],
            threshold=float(params.get("threshold") or 0.6),
            db=context.db,
            project_config=context.project_config,
        )


class GitChangeSummaryTool:
    name = "git_change_summary"
    description = "Summarize recent git history into bug-fix, refactor and feature buckets."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await resolve_runtime_service("git_change_summary")(
            cwd=cwd,
            paths=[str(item) for item in (params.get("paths") or []) if str(item).strip()],
            days=max(1, min(int(params.get("days") or 30), 365)),
            db=context.db,
            project_config=context.project_config,
        )


class GitHotspotAnalysisTool:
    name = "git_hotspot_analysis"
    description = "Highlight the riskiest frequently changing files in the repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await resolve_runtime_service("git_hotspot_analysis")(
            cwd=cwd,
            days=max(1, min(int(params.get("days") or 90), 365)),
            top_n=max(1, min(int(params.get("top_n") or 15), 50)),
            db=context.db,
            project_config=context.project_config,
        )


class GitFunctionBlameTool:
    name = "git_function_blame"
    description = "Explain ownership and recent commits for a single function, method or symbol."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        file_path = str(params.get("file") or "").strip()
        symbol = str(params.get("symbol") or "").strip()
        if not file_path or not symbol:
            return {"error": "file and symbol are required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        return await resolve_runtime_service("git_function_blame")(
            cwd=cwd,
            file_path=file_path,
            symbol=symbol,
            db=context.db,
            project_config=context.project_config,
        )


class GitConflictPredictorTool:
    name = "git_conflict_predictor"
    description = "Predict whether a planned change is incomplete or likely to collide with active work."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        planned_files = params.get("planned_files") or []
        if not isinstance(planned_files, list) or not planned_files:
            return {"error": "planned_files is required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        open_pull_requests = params.get("open_pull_requests") or []
        if not isinstance(open_pull_requests, list):
            open_pull_requests = []
        return await resolve_runtime_service("git_conflict_predictor")(
            cwd=cwd,
            planned_files=[str(item) for item in planned_files if str(item).strip()],
            open_pull_requests=open_pull_requests,
            threshold=float(params.get("threshold") or 0.6),
            db=context.db,
            project_config=context.project_config,
        )


class GitPrContextTool:
    name = "git_pr_context"
    description = "Build a complete PR context using recent history, coupling, hotspots and optional PR metadata."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        changed_files = params.get("changed_files") or []
        if not isinstance(changed_files, list) or not changed_files:
            return {"error": "changed_files is required"}
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        pr_payload = params.get("pull_request")
        if not isinstance(pr_payload, dict):
            pr_payload = None
        return await resolve_runtime_service("git_pr_context")(
            cwd=cwd,
            changed_files=[str(item) for item in changed_files if str(item).strip()],
            pr=pr_payload,
            days=max(1, min(int(params.get("days") or 90), 365)),
            db=context.db,
            project_config=context.project_config,
        )


class SelfReviewWorkspaceDiffTool:
    name = "self_review_workspace_diff"
    description = (
        "Review the current workspace diff for missing tests, secrets, debug leftovers and other pre-PR findings."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}
        changed_files = params.get("changed_files") or []
        if not isinstance(changed_files, list):
            changed_files = []
        diff_text = params.get("diff")
        if diff_text is not None:
            diff_text = str(diff_text)
        return await resolve_runtime_service("self_review_workspace_diff")(
            cwd=cwd,
            changed_files=[str(item) for item in changed_files if str(item).strip()],
            diff_text=diff_text,
        )


class BuildPullRequestDescriptionTool:
    name = "build_pull_request_description"
    description = (
        "Build a structured PR description using the project's PR template, changed files and validation results."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}

        changed_files = params.get("changed_files") or []
        if not isinstance(changed_files, list):
            changed_files = []
        test_results = params.get("test_results")
        if not isinstance(test_results, dict):
            test_results = None
        lint_results = params.get("lint_results")
        if not isinstance(lint_results, dict):
            lint_results = None
        risk_notes = params.get("risk_notes") or []
        if not isinstance(risk_notes, list):
            risk_notes = []
        return await resolve_runtime_service("build_pull_request_description")(
            cwd=cwd,
            summary=str(params.get("summary") or "").strip() or None,
            changed_files=[str(item) for item in changed_files if str(item).strip()],
            test_results=test_results,
            lint_results=lint_results,
            risk_notes=[str(item) for item in risk_notes if str(item).strip()],
            template=None,
            days=max(1, min(int(params.get("days") or 30), 365)),
        )


class GitKnowledgeExtractTool:
    name = "git_knowledge_extract"
    description = "Compress recent git history into a codebase-history knowledge payload (returned, not stored)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            cwd = _resolve_cwd(context.workspace_root, params.get("cwd"))
        except ValueError as exc:
            return {"error": str(exc)}

        extracted = await resolve_runtime_service("git_knowledge_extract")(
            cwd=cwd,
            scope=str(params.get("scope") or "."),
            extract_types=[str(item) for item in (params.get("extract_types") or []) if str(item).strip()] or None,
            days=max(1, min(int(params.get("days") or 90), 365)),
            db=context.db,
            project_config=context.project_config,
        )
        if extracted.get("error"):
            return extracted
        # Nothing is persisted here; durable repository knowledge reaches the Knowledge module
        # through its own sources.
        return {"persisted": False, **extracted}

__all__ = [
    "GitFileIntelligenceTool",
    "GitCouplingMapTool",
    "GitChangeSummaryTool",
    "GitHotspotAnalysisTool",
    "GitFunctionBlameTool",
    "GitConflictPredictorTool",
    "GitPrContextTool",
    "SelfReviewWorkspaceDiffTool",
    "BuildPullRequestDescriptionTool",
    "GitKnowledgeExtractTool",
]
