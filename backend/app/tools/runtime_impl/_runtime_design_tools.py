"""Project design artifact tools: artifacts, design context, readiness, traceability and trace sync workflows."""

from __future__ import annotations

from typing import Any

from app.services.design_artifact.crud import list_design_artifacts
from app.tools.context import ToolContext

from ...services.design_artifact_service import (
    get_project_design_context,
    get_project_design_readiness,
    get_project_design_traceability,
)
from ...services.design_delivery_sync import (
    get_project_design_trace_sync_workflows,
    run_design_trace_sync_workflow,
)


class ListProjectDesignArtifactsTool:
    name = "list_project_design_artifacts"
    description = (
        "List structured design artifacts such as outcome briefs, PRDs, acceptance criteria, "
        "ADRs and definition-of-done entries for the current project."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "database session is required"}
        project_id = str(params.get("project_id") or "").strip() or (
            context.project_ids[0] if context.project_ids else None
        )
        if not project_id:
            return {"error": "project_id is required"}
        artifact_kind = str(params.get("artifact_kind") or "").strip() or None
        status = str(params.get("status") or "").strip() or None
        items = await list_design_artifacts(
            context.db,
            project_id=project_id,
            artifact_kind=artifact_kind,
            status=status,
        )
        return {
            "project_id": project_id,
            "artifact_kind": artifact_kind or "",
            "status": status or "",
            "items": items,
            "count": len(items),
        }


class GetProjectDesignContextTool:
    name = "get_project_design_context"
    description = "Return the current project's structured design context, coverage and recommended artifacts."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "database session is required"}
        project_id = str(params.get("project_id") or "").strip() or (
            context.project_ids[0] if context.project_ids else None
        )
        if not project_id:
            return {"error": "project_id is required"}
        artifact_kind = str(params.get("artifact_kind") or "").strip() or None
        return await get_project_design_context(
            context.db,
            project_id=project_id,
            artifact_kind=artifact_kind,
        )


class GetProjectDesignReadinessTool:
    name = "get_project_design_readiness"
    description = "Return readiness blockers and coverage for the current project's required design artifacts."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "database session is required"}
        project_id = str(params.get("project_id") or "").strip() or (
            context.project_ids[0] if context.project_ids else None
        )
        if not project_id:
            return {"error": "project_id is required"}
        return await get_project_design_readiness(context.db, project_id=project_id)


class GetProjectDesignTraceabilityTool:
    name = "get_project_design_traceability"
    description = "Return the current project's artifact-to-task and artifact-to-delivery traceability summary."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "database session is required"}
        project_id = str(params.get("project_id") or "").strip() or (
            context.project_ids[0] if context.project_ids else None
        )
        if not project_id:
            return {"error": "project_id is required"}
        return await get_project_design_traceability(context.db, project_id=project_id)


class RunDesignTraceSyncWorkflowTool:
    name = "run_design_trace_sync_workflow"
    description = "Run a project-scoped design trace sync workflow such as pull-request, release or checkpoint syncing."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "database session is required"}
        project_id = str(params.get("project_id") or "").strip() or (
            context.project_ids[0] if context.project_ids else None
        )
        if not project_id:
            return {"error": "project_id is required"}
        workflow_id = str(params.get("workflow_id") or "").strip()
        if not workflow_id:
            return {"error": "workflow_id is required"}
        workflows = get_project_design_trace_sync_workflows(context.project_config)
        if not any(item["id"] == workflow_id for item in workflows):
            # fall back to the persisted project config when the caller context is stale
            result = await run_design_trace_sync_workflow(
                context.db,
                project_id=project_id,
                workflow_id=workflow_id,
                limit_per_repository=params.get("limit_per_repository"),
            )
            return result
        return await run_design_trace_sync_workflow(
            context.db,
            project_id=project_id,
            workflow_id=workflow_id,
            limit_per_repository=params.get("limit_per_repository"),
        )


__all__ = [name for name in vars() if not name.startswith("_")]
