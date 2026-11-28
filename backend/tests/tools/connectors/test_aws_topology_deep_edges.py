"""Deep wiring edges: DNS chain + event wiring derived from bounded calls."""

import pytest

from app.tools.connectors import aws_topology_deep_edges as deep
from app.tools.connectors.aws_topology_common import TopologyBuilder


class _FakeContext:
    project_config: dict = {}
    project_ids: list = []


def _responses(mapping):
    async def _call(context, builder, service, command):
        return mapping.get((service, command[0]))

    return _call


def _builder_with_inventory() -> TopologyBuilder:
    builder = TopologyBuilder(max_nodes=100)
    builder.add_node(
        "lambda_fn1", node_type="lambda_function", label="orders-worker", service="lambda",
        region="eu-central-1", arn="arn:aws:lambda:eu-central-1:1:function:orders-worker",
    )
    builder.add_node(
        "sqs_q1", node_type="sqs_queue", label="orders", service="sqs", region="eu-central-1",
    )
    builder.add_node(
        "sns_t1", node_type="sns_topic", label="alerts", service="sns", region="eu-central-1",
        arn="arn:aws:sns:eu-central-1:1:alerts",
    )
    builder.add_node(
        "lb1", node_type="load_balancer", label="app-alb", service="elbv2", region="eu-central-1",
        attributes={"dns_name": "app-alb-123.eu-central-1.elb.amazonaws.com"},
    )
    builder.add_node(
        "cf1", node_type="cloudfront_distribution", label="www.example.com", service="cloudfront",
        region="global",
        attributes={
            "domain": "d111.cloudfront.net",
            "origin_domains": ["app-alb-123.eu-central-1.elb.amazonaws.com", "assets.s3.eu-central-1.amazonaws.com"],
        },
    )
    builder.add_node(
        "s3_assets", node_type="s3_bucket", label="assets", service="s3", region="eu-central-1",
    )
    builder.add_node(
        "zone1", node_type="route53_zone", label="example.com", service="route53", region="global",
        attributes={"hosted_zone_id": "Z1", "record_count": 3},
    )
    return builder


def _edges(builder: TopologyBuilder) -> set[tuple[str, str, str]]:
    return {(e["source"], e["target"], e["type"]) for e in builder.edges}


@pytest.mark.asyncio
async def test_event_and_dns_wiring(monkeypatch):
    builder = _builder_with_inventory()
    monkeypatch.setattr(
        deep,
        "safe_aws_call",
        _responses(
            {
                ("lambda", "list-event-source-mappings"): {
                    "EventSourceMappings": [
                        {
                            "EventSourceArn": "arn:aws:sqs:eu-central-1:1:orders",
                            "FunctionArn": "arn:aws:lambda:eu-central-1:1:function:orders-worker",
                            "State": "Enabled",
                        }
                    ]
                },
                ("sns", "list-subscriptions"): {
                    "Subscriptions": [
                        {
                            "TopicArn": "arn:aws:sns:eu-central-1:1:alerts",
                            "Endpoint": "arn:aws:sqs:eu-central-1:1:orders",
                            "Protocol": "sqs",
                        }
                    ]
                },
                ("route53", "list-resource-record-sets"): {
                    "ResourceRecordSets": [
                        {
                            "Name": "www.example.com.",
                            "Type": "A",
                            "AliasTarget": {"DNSName": "d111.cloudfront.net."},
                        },
                        {
                            "Name": "api.example.com.",
                            "Type": "A",
                            "AliasTarget": {
                                "DNSName": "dualstack.app-alb-123.eu-central-1.elb.amazonaws.com."
                            },
                        },
                    ]
                },
            }
        ),
    )
    await deep.collect_deep_edges(
        _FakeContext(), builder, region="eu-central-1", max_items=25,
        services={"lambda", "sns", "route53", "cloudfront"}, include_global=True,
    )

    edges = _edges(builder)
    assert ("sqs_q1", "lambda_fn1", "triggers") in edges
    assert ("sns_t1", "sqs_q1", "delivers_to") in edges
    assert ("zone1", "cf1", "resolves_to") in edges
    assert ("zone1", "lb1", "resolves_to") in edges
    assert ("cf1", "lb1", "routes_to") in edges
    assert ("cf1", "s3_assets", "routes_to") in edges


@pytest.mark.asyncio
async def test_unmatched_targets_create_no_edges(monkeypatch):
    builder = _builder_with_inventory()
    monkeypatch.setattr(
        deep,
        "safe_aws_call",
        _responses(
            {
                ("lambda", "list-event-source-mappings"): {
                    "EventSourceMappings": [
                        {
                            "EventSourceArn": "arn:aws:kinesis:eu-central-1:1:stream/unknown",
                            "FunctionArn": "arn:aws:lambda:eu-central-1:1:function:not-discovered",
                        }
                    ]
                },
                ("sns", "list-subscriptions"): {
                    "Subscriptions": [
                        {
                            "TopicArn": "arn:aws:sns:eu-central-1:1:alerts",
                            "Endpoint": "mail@example.com",
                            "Protocol": "email",
                        }
                    ]
                },
            }
        ),
    )
    await deep.collect_deep_edges(
        _FakeContext(), builder, region="eu-central-1", max_items=25,
        services={"lambda", "sns"}, include_global=False,
    )
    assert not _edges(builder)


@pytest.mark.asyncio
async def test_record_scan_is_not_cut_by_small_max_items(monkeypatch):
    builder = _builder_with_inventory()
    filler = [
        {"Name": f"_acme-challenge-{i}.example.com.", "Type": "CNAME",
         "ResourceRecords": [{"Value": f"validation-{i}.acm.aws."}]}
        for i in range(40)
    ]
    records = filler + [
        {"Name": "www.example.com.", "Type": "A",
         "AliasTarget": {"DNSName": "d111.cloudfront.net."}}
    ]
    monkeypatch.setattr(
        deep,
        "safe_aws_call",
        _responses({("route53", "list-resource-record-sets"): {"ResourceRecordSets": records}}),
    )
    await deep.collect_deep_edges(
        _FakeContext(), builder, region="eu-central-1", max_items=5,
        services={"route53"}, include_global=True,
    )
    assert ("zone1", "cf1", "resolves_to") in _edges(builder)


@pytest.mark.asyncio
async def test_global_wiring_skipped_on_secondary_regions(monkeypatch):
    builder = _builder_with_inventory()
    calls: list[tuple[str, str]] = []

    async def _tracking(context, inner_builder, service, command):
        calls.append((service, command[0]))
        return None

    monkeypatch.setattr(deep, "safe_aws_call", _tracking)
    await deep.collect_deep_edges(
        _FakeContext(), builder, region="eu-west-1", max_items=25,
        services={"lambda", "sns", "route53", "cloudfront"}, include_global=False,
    )
    assert ("route53", "list-resource-record-sets") not in calls
    assert ("lambda", "list-event-source-mappings") in calls
