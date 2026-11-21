"""AWS serverless, audit and cost connector tools."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from typing import Any

from ...services.error_facts import error_type
from ..context import ToolContext
from .aws_core import _assume_role_if_needed, _aws_env, _aws_json, _get_boto_session
from .cloud_common import _maybe_block_connector_action_with_approval, _run_subprocess
from .common import _limit, _string


class ListAwsLambdaFunctionsTool:
    name = "list_aws_lambda_functions"
    description = "List Lambda functions in the configured AWS account and region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(context, "lambda", ["list-functions"])
        except Exception as exc:
            return {"error": str(exc)}
        functions = data.get("Functions") or []
        return {
            "count": len(functions),
            "functions": [
                {
                    "name": item.get("FunctionName"),
                    "runtime": item.get("Runtime"),
                    "handler": item.get("Handler"),
                    "last_modified": item.get("LastModified"),
                }
                for item in functions[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetAwsLambdaLogsTool:
    name = "get_aws_lambda_logs"
    description = "Read CloudWatch log events for a Lambda function."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        function_name = _string(params.get("function_name"))
        if not function_name:
            return {"error": "function_name is required"}
        log_group_name = _string(params.get("log_group_name") or f"/aws/lambda/{function_name}")
        try:
            data = await _aws_json(
                context,
                "logs",
                [
                    "filter-log-events",
                    "--log-group-name",
                    log_group_name,
                    "--limit",
                    str(_limit(context, params, 20, 100)),
                ],
            )
        except Exception as exc:
            return {"error": str(exc)}
        events = data.get("events") or []
        return {
            "function_name": function_name,
            "count": len(events),
            "events": [{"timestamp": item.get("timestamp"), "message": item.get("message")} for item in events],
        }


class InvokeAwsLambdaTool:
    name = "invoke_aws_lambda"
    description = "Invoke a Lambda function with approval."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        function_name = _string(params.get("function_name"))
        if not function_name:
            return {"error": "function_name is required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="AWS Lambda invoke", summary=f"Invoke Lambda function: {function_name}"
        )
        if blocked:
            return blocked
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("lambda")
            payload = params.get("payload")
            payload_bytes = json.dumps(payload if isinstance(payload, (dict, list)) else (payload or {})).encode()
            response = await asyncio.to_thread(
                client.invoke,
                FunctionName=function_name,
                Payload=payload_bytes,
            )
            body = response["Payload"].read().decode("utf-8", errors="replace")
        except Exception as exc:
            payload = params.get("payload")
            payload_text = json.dumps(payload if isinstance(payload, (dict, list)) else (payload or {}))
            with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as output_file:
                code, stdout, _ = await _run_subprocess(
                    [
                        "aws",
                        "lambda",
                        "invoke",
                        "--function-name",
                        function_name,
                        "--payload",
                        payload_text,
                        "--cli-binary-format",
                        "raw-in-base64-out",
                        output_file.name,
                    ],
                    env=await _aws_env(context),
                )
                if code != 0:
                    # The CLI stderr and the SDK message can carry account ids, ARNs and hosts.
                    return {
                        "error": f"aws_lambda_invoke_failed exit_code={code}",
                        "error_code": "aws_lambda_invoke_failed",
                        "exit_code": code,
                        "error_type": error_type(exc),
                    }
                output_file.seek(0)
                body = output_file.read()
            try:
                response = json.loads(stdout or "{}")
            except json.JSONDecodeError:
                response = {"raw_response": stdout}
        return {
            "function_name": function_name,
            "status_code": response.get("StatusCode"),
            "executed_version": response.get("ExecutedVersion"),
            "payload": body,
        }


class SearchAwsCloudTrailEventsTool:
    name = "search_aws_cloudtrail_events"
    description = "Search CloudTrail events."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        command = ["lookup-events", "--max-results", str(_limit(context, params, 20, 50))]
        if _string(params.get("lookup_attribute_key")) and _string(params.get("lookup_attribute_value")):
            command.extend(
                [
                    "--lookup-attributes",
                    f"AttributeKey={_string(params.get('lookup_attribute_key'))},AttributeValue={_string(params.get('lookup_attribute_value'))}",
                ]
            )
        try:
            data = await _aws_json(context, "cloudtrail", command)
        except Exception as exc:
            return {"error": str(exc)}
        events = data.get("Events") or []
        return {
            "count": len(events),
            "events": [
                {
                    "event_id": item.get("EventId"),
                    "event_name": item.get("EventName"),
                    "event_time": item.get("EventTime"),
                    "username": item.get("Username"),
                    "resources": item.get("Resources") or [],
                }
                for item in events
            ],
        }


class GetAwsCostByServiceTool:
    name = "get_aws_cost_by_service"
    description = "Get AWS cost grouped by service."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        start = _string(params.get("start") or (datetime.now(UTC).date().replace(day=1)).isoformat())
        end = _string(params.get("end") or datetime.now(UTC).date().isoformat())
        try:
            data = await _aws_json(
                context,
                "ce",
                [
                    "get-cost-and-usage",
                    "--time-period",
                    f"Start={start},End={end}",
                    "--granularity",
                    _string(params.get("granularity") or "MONTHLY"),
                    "--metrics",
                    "UnblendedCost",
                    "--group-by",
                    "Type=DIMENSION,Key=SERVICE",
                ],
            )
        except Exception as exc:
            return {"error": str(exc)}
        groups = []
        for window in data.get("ResultsByTime") or []:
            for group in window.get("Groups") or []:
                groups.append(
                    {
                        "service": (group.get("Keys") or [None])[0],
                        "amount": ((group.get("Metrics") or {}).get("UnblendedCost") or {}).get("Amount"),
                        "unit": ((group.get("Metrics") or {}).get("UnblendedCost") or {}).get("Unit"),
                    }
                )
        return {"start": start, "end": end, "count": len(groups), "costs": groups}
