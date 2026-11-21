"""AWS data connector tools."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from ...services.error_facts import error_type
from ...services.process_output_redaction import redact_process_output
from ..context import ToolContext
from .aws_core import _assume_role_if_needed, _aws_env, _aws_json, _get_boto_session
from .cloud_common import _run_subprocess
from .common import _limit, _string


class ListAwsRdsInstancesTool:
    name = "list_aws_rds_instances"
    description = "List RDS instances in the configured AWS account and region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(context, "rds", ["describe-db-instances"])
        except Exception as exc:
            return {"error": str(exc)}
        instances = data.get("DBInstances") or []
        return {
            "count": len(instances),
            "instances": [
                {
                    "identifier": item.get("DBInstanceIdentifier"),
                    "engine": item.get("Engine"),
                    "status": item.get("DBInstanceStatus"),
                    "endpoint": ((item.get("Endpoint") or {}).get("Address")),
                    "instance_class": item.get("DBInstanceClass"),
                }
                for item in instances[: _limit(context, params, default=50, maximum=200)]
            ],
        }


class GetAwsRdsMetricsTool:
    name = "get_aws_rds_metrics"
    description = "Get CloudWatch metrics for an RDS instance."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        identifier = _string(params.get("db_instance_identifier"))
        if not identifier:
            return {"error": "db_instance_identifier is required"}
        metric_name = _string(params.get("metric_name") or "CPUUtilization")
        end = datetime.now(UTC)
        start = end - timedelta(hours=int(params.get("hours") or 1))
        command = [
            "get-metric-statistics",
            "--namespace",
            "AWS/RDS",
            "--metric-name",
            metric_name,
            "--start-time",
            start.isoformat(),
            "--end-time",
            end.isoformat(),
            "--period",
            str(int(params.get("period_seconds") or 300)),
            "--statistics",
            _string(params.get("statistic") or "Average"),
            "--dimensions",
            f"Name=DBInstanceIdentifier,Value={identifier}",
        ]
        try:
            data = await _aws_json(context, "cloudwatch", command)
        except Exception as exc:
            return {"error": str(exc)}
        return {
            "db_instance_identifier": identifier,
            "metric_name": metric_name,
            "count": len(data.get("Datapoints") or []),
            "datapoints": data.get("Datapoints") or [],
        }


class GetAwsRdsSlowQueriesTool:
    name = "get_aws_rds_slow_queries"
    description = "Read RDS slow query log output."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        identifier = _string(params.get("db_instance_identifier"))
        log_file_name = _string(params.get("log_file_name"))
        if not identifier or not log_file_name:
            return {"error": "db_instance_identifier and log_file_name are required"}
        try:
            session = _get_boto_session(context)
            session = await _assume_role_if_needed(context, session)
            client = session.client("rds")
            response = await asyncio.to_thread(
                client.download_db_log_file_portion,
                DBInstanceIdentifier=identifier,
                LogFileName=log_file_name,
            )
            log_data = response.get("LogFileData", "")
        except Exception as exc:
            code, stdout, _ = await _run_subprocess(
                [
                    "aws",
                    "rds",
                    "download-db-log-file-portion",
                    "--db-instance-identifier",
                    identifier,
                    "--log-file-name",
                    log_file_name,
                    "--output",
                    "text",
                ],
                env=await _aws_env(context),
            )
            if code != 0:
                # The CLI stderr and the SDK message can carry account ids, ARNs and hosts.
                return {
                    "error": f"aws_rds_log_download_failed exit_code={code}",
                    "error_code": "aws_rds_log_download_failed",
                    "exit_code": code,
                    "error_type": error_type(exc),
                }
            # The log portion is the product result the agent asked for; kept through the redactor.
            log_data = redact_process_output(stdout)
        lines = [line for line in log_data.splitlines() if line.strip()]
        limit = _limit(context, params, default=50, maximum=500)
        return {
            "db_instance_identifier": identifier,
            "log_file_name": log_file_name,
            "count": len(lines[:limit]),
            "lines": lines[:limit],
        }
