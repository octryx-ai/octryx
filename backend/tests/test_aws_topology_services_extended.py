"""Extended AWS service collectors: parsing + graceful degradation."""

import pytest

from app.tools.connectors import aws_topology_services_extended as ext
from app.tools.connectors import aws_topology_vpc_services as vpc_services
from app.tools.connectors.aws_topology_common import TopologyBuilder


class _FakeContext:
    project_config: dict = {}
    project_ids: list = []


def _responses(mapping):
    async def _call(context, builder, service, command):
        return mapping.get((service, command[0]))

    return _call


@pytest.mark.asyncio
async def test_regional_services_are_collected(monkeypatch):
    builder = TopologyBuilder(max_nodes=100)
    monkeypatch.setattr(
        ext,
        "safe_aws_call",
        _responses(
            {
                ("sqs", "list-queues"): {
                    "QueueUrls": ["https://sqs.eu-central-1.amazonaws.com/1/orders.fifo"]
                },
                ("sns", "list-topics"): {"Topics": [{"TopicArn": "arn:aws:sns:eu:1:alerts"}]},
                ("route53", "list-hosted-zones"): {
                    "HostedZones": [{"Id": "/hostedzone/Z1", "Name": "example.com.",
                                     "Config": {"PrivateZone": False}, "ResourceRecordSetCount": 12}]
                },
                ("ecr", "describe-repositories"): {
                    "repositories": [{"repositoryName": "app/api", "repositoryArn": "arn:ecr:app/api"}]
                },
            }
        ),
    )
    await ext.discover_sqs(_FakeContext(), builder, region="eu-central-1", max_items=25)
    await ext.discover_sns(_FakeContext(), builder, region="eu-central-1", max_items=25)
    await ext.discover_route53(_FakeContext(), builder, region="eu-central-1", max_items=25)
    await ext.discover_ecr(_FakeContext(), builder, region="eu-central-1", max_items=25)

    by_type = {n["type"]: n for n in builder.nodes.values()}
    assert by_type["sqs_queue"]["label"] == "orders.fifo"
    assert by_type["sqs_queue"]["attributes"]["fifo"] is True
    assert by_type["sns_topic"]["label"] == "alerts"
    assert by_type["route53_zone"]["label"] == "example.com"
    assert by_type["ecr_repository"]["label"] == "app/api"


@pytest.mark.asyncio
async def test_vpc_bound_service_links_subnet_and_vpc(monkeypatch):
    builder = TopologyBuilder(max_nodes=100)
    monkeypatch.setattr(
        vpc_services,
        "safe_aws_call",
        _responses(
            {
                ("efs", "describe-file-systems"): {
                    "FileSystems": [{"FileSystemId": "fs-1", "Name": "shared",
                                     "FileSystemArn": "arn:efs:fs-1", "LifeCycleState": "available"}]
                },
                ("efs", "describe-mount-targets"): {
                    "MountTargets": [{"SubnetId": "subnet-a", "VpcId": "vpc-1"},
                                     {"SubnetId": "subnet-b", "VpcId": "vpc-1"}]
                },
            }
        ),
    )
    await vpc_services.discover_efs(_FakeContext(), builder, region="eu-central-1", max_items=25)

    fs = next(n for n in builder.nodes.values() if n["type"] == "efs_file_system")
    assert fs["label"] == "shared"
    edge_targets = {(e["type"], e["target"]) for e in builder.edges}
    assert ("uses_subnet", "subnet:subnet-a") in edge_targets
    assert ("uses_subnet", "subnet:subnet-b") in edge_targets
    assert ("runs_in", "vpc:vpc-1") in edge_targets


@pytest.mark.asyncio
async def test_missing_service_degrades_without_nodes(monkeypatch):
    builder = TopologyBuilder(max_nodes=100)
    # safe_aws_call returns None for everything (unauthorized / unused service)
    monkeypatch.setattr(ext, "safe_aws_call", _responses({}))
    monkeypatch.setattr(vpc_services, "safe_aws_call", _responses({}))
    await vpc_services.discover_ecs(_FakeContext(), builder, region="eu-central-1", max_items=25)
    await vpc_services.discover_elasticache(_FakeContext(), builder, region="eu-central-1", max_items=25)
    await ext.discover_apigateway(_FakeContext(), builder, region="eu-central-1", max_items=25)
    assert builder.nodes == {}
