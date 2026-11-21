"""AWS CodePipeline and WAFv2 connector tools."""

from __future__ import annotations

import asyncio
from typing import Any

from ..context import ToolContext
from .aws_core import _assume_role_if_needed, _aws_json, _get_boto_session, _sanitize_datetimes
from .cloud_common import _maybe_block_connector_action_with_approval
from .common import _limit, _string


class ListAwsCodePipelinesTool:
    name = "list_aws_codepipelines"
    description = "List CodePipeline pipelines in the configured AWS account/region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(context, "codepipeline", ["list-pipelines"])
        except Exception as exc:
            return {"error": str(exc)}
        pipelines = data.get("pipelines") or []
        return {
            "count": len(pipelines),
            "pipelines": [
                {
                    "name": item.get("name"),
                    "version": item.get("version"),
                    "created": str(item.get("created", "")),
                    "updated": str(item.get("updated", "")),
                }
                for item in pipelines[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetAwsCodePipelineStateTool:
    name = "get_aws_codepipeline_state"
    description = "Get the current execution state of a CodePipeline pipeline including stage and action statuses."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pipeline_name = _string(params.get("pipeline_name"))
        if not pipeline_name:
            return {"error": "pipeline_name is required"}
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("codepipeline")
            data = await asyncio.to_thread(client.get_pipeline_state, name=pipeline_name)
        except Exception as exc:
            return {"error": str(exc)}
        stages = data.get("stageStates") or []
        return _sanitize_datetimes({
            "pipeline_name": data.get("pipelineName"),
            "pipeline_version": data.get("pipelineVersion"),
            "stages": [
                {
                    "stage_name": s.get("stageName"),
                    "status": (s.get("latestExecution") or {}).get("status"),
                    "actions": [
                        {
                            "action_name": a.get("actionName"),
                            "status": (a.get("latestExecution") or {}).get("status"),
                            "last_status_change": str((a.get("latestExecution") or {}).get("lastStatusChange") or ""),
                            "error_details": (a.get("latestExecution") or {}).get("errorDetails"),
                        }
                        for a in s.get("actionStates") or []
                    ],
                }
                for s in stages
            ],
        })


class ListAwsCodePipelineExecutionsTool:
    name = "list_aws_codepipeline_executions"
    description = "List recent executions of a CodePipeline pipeline."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pipeline_name = _string(params.get("pipeline_name"))
        if not pipeline_name:
            return {"error": "pipeline_name is required"}
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("codepipeline")
            data = await asyncio.to_thread(
                client.list_pipeline_executions,
                pipelineName=pipeline_name,
                maxResults=_limit(context, params, default=10, maximum=50),
            )
        except Exception as exc:
            return {"error": str(exc)}
        executions = data.get("pipelineExecutionSummaries") or []
        return _sanitize_datetimes({
            "pipeline_name": pipeline_name,
            "count": len(executions),
            "executions": [
                {
                    "execution_id": item.get("pipelineExecutionId"),
                    "status": item.get("status"),
                    "start_time": str(item.get("startTime", "")),
                    "last_update_time": str(item.get("lastUpdateTime", "")),
                    "trigger": (item.get("trigger") or {}).get("triggerType"),
                }
                for item in executions
            ],
        })


class StartAwsCodePipelineExecutionTool:
    name = "start_aws_codepipeline_execution"
    description = "Start a new execution of a CodePipeline pipeline (requires approval)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pipeline_name = _string(params.get("pipeline_name"))
        if not pipeline_name:
            return {"error": "pipeline_name is required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="AWS CodePipeline execution", summary=f"Start pipeline: {pipeline_name}"
        )
        if blocked:
            return blocked
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("codepipeline")
            data = await asyncio.to_thread(client.start_pipeline_execution, name=pipeline_name)
        except Exception as exc:
            return {"error": str(exc)}
        return {
            "pipeline_name": pipeline_name,
            "execution_id": data.get("pipelineExecutionId"),
        }


class ListAwsWafWebAclsTool:
    name = "list_aws_waf_web_acls"
    description = "List WAFv2 Web ACLs in the configured AWS account/region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = _string(params.get("scope")) or "REGIONAL"
        if scope.upper() not in ("REGIONAL", "CLOUDFRONT"):
            return {"error": "scope must be REGIONAL or CLOUDFRONT"}
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("wafv2")
            data = await asyncio.to_thread(client.list_web_acls, Scope=scope.upper())
        except Exception as exc:
            return {"error": str(exc)}
        acls = data.get("WebACLs") or []
        return {
            "count": len(acls),
            "web_acls": [
                {
                    "name": item.get("Name"),
                    "id": item.get("Id"),
                    "arn": item.get("ARN"),
                }
                for item in acls[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetAwsWafWebAclTool:
    name = "get_aws_waf_web_acl"
    description = "Get details of a WAFv2 Web ACL including rules."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        name = _string(params.get("name"))
        acl_id = _string(params.get("id"))
        scope = _string(params.get("scope")) or "REGIONAL"
        if not name or not acl_id:
            return {"error": "name and id are required"}
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("wafv2")
            data = await asyncio.to_thread(client.get_web_acl, Name=name, Scope=scope.upper(), Id=acl_id)
        except Exception as exc:
            return {"error": str(exc)}
        acl = data.get("WebACL") or {}
        rules = acl.get("Rules") or []
        return _sanitize_datetimes({
            "name": acl.get("Name"),
            "id": acl.get("Id"),
            "arn": acl.get("ARN"),
            "capacity": acl.get("Capacity"),
            "default_action": acl.get("DefaultAction"),
            "rules_count": len(rules),
            "rules": [
                {
                    "name": r.get("Name"),
                    "priority": r.get("Priority"),
                    "action": r.get("Action") or r.get("OverrideAction"),
                }
                for r in rules
            ],
        })
