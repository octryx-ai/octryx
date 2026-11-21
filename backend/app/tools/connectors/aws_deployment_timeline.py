"""AWS deployment timeline connector tool."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .aws_topology_common import bounded_int
from .common import _normalize_string_list, _string

MAX_PIPELINES = 20
MAX_EXECUTIONS_PER_PIPELINE = 20


def _pipeline_names(params: dict[str, Any]) -> list[str]:
    return _normalize_string_list(params.get("pipeline_names") or params.get("pipelines"))[:MAX_PIPELINES]


def _execution_event(pipeline_name: str, execution: dict[str, Any]) -> dict[str, Any]:
    status = _string(execution.get("status")) or "unknown"
    return {
        "timestamp": execution.get("startTime") or execution.get("lastUpdateTime"),
        "event_type": "codepipeline_execution",
        "source": "codepipeline",
        "pipeline_name": pipeline_name,
        "execution_id": execution.get("pipelineExecutionId"),
        "status": status,
        "severity": "warning" if status.lower() in {"failed", "stopped", "superseded"} else "info",
        "summary": f"CodePipeline {pipeline_name} execution {status}",
        "details": {
            "start_time": execution.get("startTime"),
            "last_update_time": execution.get("lastUpdateTime"),
            "source_revisions": execution.get("sourceRevisions") or [],
        },
        "evidence": [
            {
                "service": "codepipeline",
                "operation": "list-pipeline-executions",
                "pipeline_name": pipeline_name,
                "direct": True,
            }
        ],
    }


def _sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: str(item.get("timestamp") or ""), reverse=True)


async def _list_pipelines(context: ToolContext) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        data = await _aws_json(context, "codepipeline", ["list-pipelines"])
    except Exception as exc:
        return [], [{"severity": "warning", "message": f"CodePipeline list-pipelines failed: {exc}"}]
    pipelines = data.get("pipelines") if isinstance(data, dict) else []
    names = [_string(item.get("name")) for item in pipelines or [] if isinstance(item, dict) and item.get("name")]
    return names[:MAX_PIPELINES], []


async def build_aws_deployment_timeline(context: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    warnings = []
    pipeline_names = _pipeline_names(params)
    if not pipeline_names:
        pipeline_names, list_warnings = await _list_pipelines(context)
        warnings.extend(list_warnings)

    per_pipeline = bounded_int(
        params.get("max_executions_per_pipeline"),
        default=10,
        maximum=MAX_EXECUTIONS_PER_PIPELINE,
    )
    events = []
    for name in pipeline_names:
        try:
            data = await _aws_json(
                context,
                "codepipeline",
                ["list-pipeline-executions", "--pipeline-name", name, "--max-results", str(per_pipeline)],
            )
        except Exception as exc:
            warnings.append({"severity": "warning", "message": f"CodePipeline executions failed for {name}: {exc}"})
            continue
        for execution in data.get("pipelineExecutionSummaries") or []:
            if isinstance(execution, dict):
                events.append(_execution_event(name, execution))

    events = _sort_events(events)
    return {
        "status": "ok",
        "sources": ["codepipeline"],
        "pipeline_names": pipeline_names,
        "summary": {
            "event_count": len(events),
            "pipeline_count": len(pipeline_names),
            "warning_count": len(warnings),
        },
        "events": events,
        "warnings": warnings,
    }


class AwsDeploymentTimelineTool:
    name = "aws_deployment_timeline"
    description = (
        "Produce a bounded chronological deployment evidence timeline from AWS deployment sources. "
        "The first slice uses read-only CodePipeline execution history."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await build_aws_deployment_timeline(context, params or {})
