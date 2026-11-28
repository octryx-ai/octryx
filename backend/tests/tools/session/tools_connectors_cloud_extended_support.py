"""Fake AWS CLI, Azure management and Google Cloud APIs behind the extended cloud connector tool tests."""

import asyncio
from pathlib import Path

AZURE_VM_ID = "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod"

_EC2_INSTANCES = {
    "Reservations": [
        {
            "Instances": [
                {
                    "InstanceId": "i-123",
                    "State": {"Name": "running"},
                    "InstanceType": "t3.small",
                    "PrivateIpAddress": "10.0.0.5",
                    "Tags": [{"Key": "Name", "Value": "web01"}],
                }
            ]
        }
    ]
}
_RDS_INSTANCES = {
    "DBInstances": [
        {
            "DBInstanceIdentifier": "db-main",
            "Engine": "postgres",
            "DBInstanceStatus": "available",
            "Endpoint": {"Address": "db.example"},
            "DBInstanceClass": "db.t4g.medium",
        }
    ]
}
_LAMBDA_FUNCTIONS = {
    "Functions": [
        {
            "FunctionName": "acme-orders-handler",
            "Runtime": "python3.12",
            "Handler": "handler.main",
            "LastModified": "2026-03-28",
        }
    ]
}
_CLOUDTRAIL_EVENTS = {
    "Events": [
        {
            "EventId": "evt-1",
            "EventName": "UpdateFunctionCode",
            "EventTime": "2026-03-28T00:00:00Z",
            "Username": "ops",
            "Resources": [],
        }
    ]
}
_COST_AND_USAGE = {
    "ResultsByTime": [
        {"Groups": [{"Keys": ["AmazonEC2"], "Metrics": {"UnblendedCost": {"Amount": "12.34", "Unit": "USD"}}}]}
    ]
}
_GCE_AGGREGATED_INSTANCES = {
    "items": {
        "zones/europe-west3-b": {
            "instances": [
                {
                    "name": "gce-1",
                    "id": "1001",
                    "zone": "zones/europe-west3-b",
                    "status": "RUNNING",
                    "machineType": "n2-standard-2",
                }
            ]
        }
    }
}
_CLOUD_SQL_INSTANCES = {
    "items": [
        {
            "name": "sql-prod",
            "databaseVersion": "POSTGRES_15",
            "region": "europe-west3",
            "state": "RUNNABLE",
        }
    ]
}
_CLOUD_RUN_SERVICES = {
    "services": [
        {
            "name": "projects/proj/locations/europe-west3/services/api",
            "uri": "https://api.run.app",
            "ingress": "INGRESS_TRAFFIC_ALL",
            "reconciling": False,
        }
    ]
}


async def _allow_grant(*args, **kwargs):
    return True


async def _fake_aws_json(context, service, command):
    if service == "ec2" and command == ["describe-instances"]:
        return _EC2_INSTANCES
    if service == "ec2" and command[:1] == ["start-instances"]:
        return {"StartingInstances": [{"InstanceId": "i-123", "CurrentState": {"Name": "pending"}}]}
    if service == "ec2" and command[:1] == ["stop-instances"]:
        return {"StoppingInstances": [{"InstanceId": "i-123", "CurrentState": {"Name": "stopping"}}]}
    if service == "logs" and command[:1] == ["filter-log-events"]:
        return {"events": [{"timestamp": 123, "message": "instance log line", "logStreamName": "stream-1"}]}
    if service == "rds" and command == ["describe-db-instances"]:
        return _RDS_INSTANCES
    if service == "cloudwatch" and command[:1] == ["get-metric-statistics"]:
        return {"Datapoints": [{"Average": 42.0, "Timestamp": "2026-03-28T00:00:00Z"}]}
    if service == "lambda" and command == ["list-functions"]:
        return _LAMBDA_FUNCTIONS
    if service == "cloudtrail" and command[:1] == ["lookup-events"]:
        return _CLOUDTRAIL_EVENTS
    if service == "ce" and command[:1] == ["get-cost-and-usage"]:
        return _COST_AND_USAGE
    raise AssertionError(f"Unexpected AWS call {service} {command}")


async def _fake_run_subprocess(command, *, env=None):
    command_text = " ".join(command)
    if "download-db-log-file-portion" in command_text:
        return 0, "slow query 1\nslow query 2\n", ""
    if "lambda invoke" in command_text:
        output_path = command[-1]
        Path(output_path).write_text('{"ok": true}', encoding="utf-8")
        return 0, '{"StatusCode": 200, "ExecutedVersion": "$LATEST"}', ""
    raise AssertionError(f"Unexpected subprocess {command}")


async def _fake_azure_token(context):
    return "azure-token"


async def _fake_gcp_access_token(context):
    return "gcp-token"


def _azure_response(url):
    if url.endswith("/virtualMachines"):
        return {"value": [{"name": "vm-prod", "location": "westeurope", "id": AZURE_VM_ID}]}
    if url.endswith("/start") or url.endswith("/deallocate"):
        return {}
    if "AlertsManagement/alerts" in url:
        return {"value": [{"name": "cpu-alert", "properties": {"severity": "Sev2", "monitorCondition": "Fired"}}]}
    if url.endswith("/providers/microsoft.insights/metrics"):
        return {"value": [{"name": {"value": "Percentage CPU"}, "timeseries": []}]}
    if url.endswith("/providers/Microsoft.CostManagement/query"):
        return {"properties": {"rows": [["2026-03-28", 14.5]]}}
    return None


def _gcp_response(url):
    if "compute.googleapis.com" in url:
        return _GCE_AGGREGATED_INSTANCES
    if "logging.googleapis.com" in url:
        return {"entries": [{"timestamp": "2026-03-28T00:00:00Z", "textPayload": "log line"}]}
    if "sqladmin.googleapis.com" in url:
        return _CLOUD_SQL_INSTANCES
    if "monitoring.googleapis.com" in url:
        return {"timeSeries": [{"metric": {"type": "cloudsql.googleapis.com/database/cpu/utilization"}}]}
    if "run.googleapis.com" in url:
        return _CLOUD_RUN_SERVICES
    return None


async def _fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
    if "management.azure.com" in url:
        assert headers["Authorization"].startswith("Bearer azure-token")
        response = _azure_response(url)
        if response is not None:
            return response
    response = _gcp_response(url)
    if response is not None:
        return response
    raise AssertionError(f"Unexpected HTTP call {method} {url}")


# The connector modules that look each helper up (each imports it from its defining module).
_LOOKUPS = {
    "consume_change_preview_grant": ("cloud_common",),
    "_aws_json": (
        "aws_compute", "aws_config_query", "aws_core", "aws_cost_topology", "aws_data", "aws_deployment_timeline",
        "aws_lambda", "aws_pipeline", "aws_topology_common", "aws_trusted_advisor",
    ),
    "_run_subprocess": ("aws_data", "aws_gateway", "aws_lambda", "cloud_common"),
    "_azure_token": ("azure",),
    "_gcp_access_token": ("gcp", "gcp_core"),
    "_aws_env": ("aws_core", "aws_data", "aws_gateway", "aws_lambda"),
}


def patch_cloud_connectors(monkeypatch) -> None:
    fakes = {
        "consume_change_preview_grant": _allow_grant,
        "_aws_json": _fake_aws_json,
        "_run_subprocess": _fake_run_subprocess,
        "_azure_token": _fake_azure_token,
        "_gcp_access_token": _fake_gcp_access_token,
        "_aws_env": lambda context: asyncio.sleep(0, result={}),
    }
    for helper, modules in _LOOKUPS.items():
        for module in modules:
            monkeypatch.setattr(f"app.tools.connectors.{module}.{helper}", fakes[helper])
    monkeypatch.setattr("app.tools.connectors.common._http_json", _fake_http_json)
    monkeypatch.setattr("shutil.which", lambda command: "/usr/bin/aws" if command == "aws" else None)
