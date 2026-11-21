"""AWS compute and platform connector tools."""

from __future__ import annotations

from typing import Any

from ..context import ToolContext
from .aws_core import _aws_json
from .cloud_common import _maybe_block_connector_action_with_approval
from .common import _limit, _normalize_string_list, _string


class ListAwsEksClustersTool:
    name = "list_aws_eks_clusters"
    description = "List EKS clusters in the configured AWS account/region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(context, "eks", ["list-clusters"])
        except Exception as exc:
            return {"error": str(exc)}
        clusters = data.get("clusters") or []
        return {"count": len(clusters), "clusters": clusters}


class ListAwsCloudWatchAlarmsTool:
    name = "list_aws_cloudwatch_alarms"
    description = "List CloudWatch alarms in the configured AWS account/region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(
                context, "cloudwatch", ["describe-alarms", "--max-records", str(_limit(context, params, 20, 100))]
            )
        except Exception as exc:
            return {"error": str(exc)}
        alarms = data.get("MetricAlarms") or []
        return {
            "count": len(alarms),
            "alarms": [
                {
                    "name": item.get("AlarmName"),
                    "state": item.get("StateValue"),
                    "reason": item.get("StateReason"),
                    "updated_at": item.get("StateUpdatedTimestamp"),
                }
                for item in alarms
            ],
        }


class ListAwsEc2InstancesTool:
    name = "list_aws_ec2_instances"
    description = "List EC2 instances in the configured AWS account and region."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        try:
            data = await _aws_json(context, "ec2", ["describe-instances"])
        except Exception as exc:
            return {"error": str(exc)}
        instances: list[dict[str, Any]] = []
        for reservation in data.get("Reservations") or []:
            for item in reservation.get("Instances") or []:
                instances.append(
                    {
                        "instance_id": item.get("InstanceId"),
                        "state": ((item.get("State") or {}).get("Name")),
                        "instance_type": item.get("InstanceType"),
                        "private_ip": item.get("PrivateIpAddress"),
                        "public_ip": item.get("PublicIpAddress"),
                        "name": next(
                            (tag.get("Value") for tag in item.get("Tags") or [] if tag.get("Key") == "Name"), None
                        ),
                    }
                )
        return {"count": len(instances), "instances": instances[: _limit(context, params, default=50, maximum=200)]}


class StartAwsEc2InstancesTool:
    name = "start_aws_ec2_instances"
    description = "Start one or more EC2 instances with approval."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        instance_ids = _normalize_string_list(params.get("instance_ids"))
        if not instance_ids:
            return {"error": "instance_ids are required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="AWS EC2 start", summary=f"Start EC2 instances: {', '.join(instance_ids)}"
        )
        if blocked:
            return blocked
        try:
            data = await _aws_json(context, "ec2", ["start-instances", "--instance-ids", *instance_ids])
        except Exception as exc:
            return {"error": str(exc)}
        return {"status": "started", "instances": data.get("StartingInstances") or []}


class StopAwsEc2InstancesTool:
    name = "stop_aws_ec2_instances"
    description = "Stop one or more EC2 instances with approval."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        instance_ids = _normalize_string_list(params.get("instance_ids"))
        if not instance_ids:
            return {"error": "instance_ids are required"}
        blocked = await _maybe_block_connector_action_with_approval(
            self.name, params, context, title="AWS EC2 stop", summary=f"Stop EC2 instances: {', '.join(instance_ids)}"
        )
        if blocked:
            return blocked
        try:
            data = await _aws_json(context, "ec2", ["stop-instances", "--instance-ids", *instance_ids])
        except Exception as exc:
            return {"error": str(exc)}
        return {"status": "stopped", "instances": data.get("StoppingInstances") or []}


class GetAwsEc2LogsTool:
    name = "get_aws_ec2_logs"
    description = "Read CloudWatch log events for an EC2 workload log group."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        log_group_name = _string(params.get("log_group_name"))
        if not log_group_name:
            return {"error": "log_group_name is required"}
        command = [
            "filter-log-events",
            "--log-group-name",
            log_group_name,
            "--limit",
            str(_limit(context, params, 20, 100)),
        ]
        log_stream_names = _normalize_string_list(params.get("log_stream_names"))
        if log_stream_names:
            command.extend(["--log-stream-names", *log_stream_names])
        try:
            data = await _aws_json(context, "logs", command)
        except Exception as exc:
            return {"error": str(exc)}
        events = data.get("events") or []
        return {
            "log_group_name": log_group_name,
            "count": len(events),
            "events": [
                {
                    "timestamp": item.get("timestamp"),
                    "message": item.get("message"),
                    "log_stream_name": item.get("logStreamName"),
                }
                for item in events
            ],
        }
