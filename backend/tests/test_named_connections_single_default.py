"""Without named connections, a call naming a key the default entry does not declare is refused.

A descriptor whose default entry declares its key (``default_key_fields``: Kubernetes ``k8s_context``, AWS
``aws_account_id``, GCP ``gcp_project_id``) serves only that key; a call naming another cluster, account or
project would otherwise run on the default's account. A default that declares no key keeps today's
behaviour (the call passes through), and so does a call that names no key or exactly the declared one.
"""

from __future__ import annotations

import pytest

from app.services.named_connections.descriptors import DESCRIPTORS, routed_tool_names
from app.services.named_connections.route_planner import plan_route, planned_connection_ids

# (connector, the default's declared key field, the request parameter naming the key, declared, other)
CASES = [
    ("kubernetes", "k8s_context", "cluster", "prod", "demo-other"),
    ("aws", "aws_account_id", "account_id", "123456789012", "210987654321"),
    ("gcp", "gcp_project_id", "project_id", "prod-4711", "demo-other-4711"),
]


def _tool(connector: str) -> str:
    return sorted(routed_tool_names(connector))[0]


def test_every_descriptor_with_a_declared_default_key_is_covered() -> None:
    declared = {connector for connector, descriptor in DESCRIPTORS.items() if descriptor.default_key_fields}
    assert declared == {case[0] for case in CASES}


@pytest.mark.parametrize(("connector", "field", "param", "own", "other"), CASES)
def test_another_key_than_the_declared_one_is_refused(connector, field, param, own, other) -> None:
    plan = plan_route(_tool(connector), {param: other}, {field: own})
    assert plan.refusal is not None
    assert plan.refusal["code"] == "connection_not_configured_for_scope"
    assert plan.refusal["connection_id"] == "default" and plan.refusal["scopes"] == [
        DESCRIPTORS[connector].scope_key(other)]
    # The declared value is named so the model can retry with it.
    own_key = DESCRIPTORS[connector].scope_key(own)
    assert plan.refusal["served_scopes"] == [own_key] and f": {own_key};" in plan.refusal["error"]
    assert planned_connection_ids(_tool(connector), {param: other}, {field: own}) == ()
    # An explicit default connection does not lift it.
    assert plan_route(_tool(connector), {param: other, "connection": "default"}, {field: own}).refusal is not None


@pytest.mark.parametrize(("connector", "field", "param", "own", "other"), CASES)
def test_the_declared_key_no_key_or_an_empty_declaration_pass_through(connector, field, param, own, other) -> None:
    tool = _tool(connector)
    assert plan_route(tool, {param: own}, {field: own}).passthrough
    assert plan_route(tool, {}, {field: own}).passthrough
    for empty in ({}, {field: ""}, {field: "  "}):
        plan = plan_route(tool, {param: other}, empty)
        assert plan.passthrough and plan.refusal is None, empty


def test_a_value_a_secret_field_also_holds_is_never_named() -> None:
    descriptor = DESCRIPTORS["aws"]
    [secret] = descriptor.secret_fields[:1] or pytest.skip("aws declares no secret field")
    config = {"aws_account_id": "123456789012", secret: "123456789012"}
    plan = plan_route(_tool("aws"), {"account_id": "210987654321"}, config)
    assert plan.refusal["served_scopes"] == []
    assert "123456789012" not in plan.refusal["error"]


def test_an_allowlist_connector_is_left_to_its_own_rules() -> None:
    plan = plan_route("search_confluence", {"space_key": "OTHER"}, {"confluence_allowed_spaces": ["SALES"]})
    assert plan.passthrough
