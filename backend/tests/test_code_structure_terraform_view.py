"""Dedicated Terraform infrastructure views: module-overview inventory board
plus per-module detail diagrams with provider-mapped aws4 icons."""

import json

from app.services.diagrams.code_structure_terraform_icons import (
    aws_node_type,
    node_visual,
)
from app.services.diagrams.code_structure_terraform_view import (
    build_terraform_diagram_tool_calls,
    build_terraform_module_detail_ir,
    build_terraform_module_overview_ir,
    snapshot_is_terraform,
    terraform_detail_packages,
)


def _node(ref, kind, label, package, resource_type="", provider="", file=""):
    attributes = {"block": kind, "package": package, "file": file or "main.tf"}
    if resource_type:
        attributes["resource_type"] = resource_type
        attributes["provider"] = provider or "aws"
    return {"ref": ref, "type": kind, "label": label, "attributes": attributes}


def _snapshot():
    return {
        "workspace": "/tmp/workspace",
        "service_summary": {
            "file_count": 2,
            "class_count": 8,
            "package_count": 2,
            "counts_by_language": {"terraform": 2},
        },
        "diagram_brief": {
            "selected_nodes": [
                _node("class:aws_lb.app", "resource", "aws_lb.app", "", "aws_lb"),
                _node("class:aws_foo_bar.x", "resource", "aws_foo_bar.x", "", "aws_foo_bar"),
                _node("class:module.network", "module", "module.network", ""),
                _node(
                    "class:modules.network.aws_vpc.main",
                    "resource",
                    "aws_vpc.main",
                    "modules.network",
                    "aws_vpc",
                    file="modules/network/vpc.tf",
                ),
                _node(
                    "class:modules.network.azurerm_lb.edge",
                    "resource",
                    "azurerm_lb.edge",
                    "modules.network",
                    "azurerm_lb",
                    provider="azurerm",
                    file="modules/network/azure.tf",
                ),
                _node("class:var.vpc_cidr", "variable", "var.vpc_cidr", ""),
                _node("class:output.alb_dns", "output", "output.alb_dns", ""),
                {
                    "ref": "package:modules.network",
                    "type": "package",
                    "label": "modules.network",
                    "attributes": {"class_count": 2, "selected_count": 2},
                },
            ],
            "selected_edges": [
                {"source_ref": "class:aws_lb.app", "target_ref": "class:module.network", "type": "uses"},
                {"source_ref": "class:aws_lb.app", "target_ref": "class:var.vpc_cidr", "type": "uses"},
                {
                    "source_ref": "class:modules.network.aws_vpc.main",
                    "target_ref": "package:modules.network",
                    "type": "belongs_to",
                },
            ],
            "truncated": False,
        },
        "warnings": [],
    }


def test_snapshot_is_terraform_requires_language_evidence():
    assert snapshot_is_terraform(_snapshot())
    assert not snapshot_is_terraform(
        {"service_summary": {"counts_by_language": {"java": 3}}, "diagram_brief": {}}
    )
    assert not snapshot_is_terraform(None)
    assert not snapshot_is_terraform({})


def test_node_visual_maps_official_aws4_shapes():
    label, style, _w, _h = node_visual(_node("r", "resource", "aws_lb.app", "", "aws_lb"))
    assert label == "app\naws_lb"
    assert "shape=mxgraph.aws4.resourceIcon" in style
    assert "resIcon=mxgraph.aws4.application_load_balancer" in style
    assert "fillColor=#8C4FFF" in style  # networking category fill


def test_node_visual_generic_fallback_and_provider_boxes():
    _label, style, _w, _h = node_visual(_node("r", "resource", "aws_foo_bar.x", "", "aws_foo_bar"))
    assert "resIcon=mxgraph.aws4.general" in style
    _label, azure_style, _w, _h = node_visual(
        _node("r", "resource", "azurerm_lb.edge", "", "azurerm_lb", provider="azurerm")
    )
    assert "mxgraph.aws4" not in azure_style
    assert "strokeColor=#0078d4" in azure_style


def test_unseen_sub_resources_inherit_family_icon():
    # exact table wins
    assert aws_node_type("aws_db_proxy") == "rds_proxy"
    # unseen sub-resources resolve via the longest-prefix family fallback
    assert aws_node_type("aws_iam_access_key") == "iam_role"
    assert aws_node_type("aws_s3_bucket_versioning") == "s3_bucket"
    assert aws_node_type("aws_route53_health_check") == "route53_zone"
    assert aws_node_type("aws_lambda_permission") == "lambda_function"
    # longest prefix wins over the shorter family
    assert aws_node_type("aws_vpc_endpoint_policy") == "vpc_endpoint"
    assert aws_node_type("aws_vpc_ipv4_cidr_block_association") == "vpc"
    # metadata data sources stay generic on purpose
    assert aws_node_type("aws_region") == ""


def test_overview_shows_every_module_directory():
    diagram = build_terraform_module_overview_ir({}, _snapshot())
    assert diagram is not None
    cards = [node for node in diagram.nodes if node.id.startswith("tf_card")]
    headers = [node.label.splitlines()[0] for node in cards]
    # both directories present, largest first — no container cap involved
    assert headers[0].startswith("root module - 5 blocks")
    assert headers[1].startswith("modules.network - 2 blocks")


def test_overview_cards_state_counts_and_providers():
    diagram = build_terraform_module_overview_ir({}, _snapshot())
    cards = {
        node.label.splitlines()[0].split(" - ")[0]: node.label
        for node in diagram.nodes
        if node.id.startswith("tf_card")
    }
    root_card = cards["root module"]
    assert "2 resources" in root_card and "1 module" in root_card
    assert "1 variable" in root_card and "1 output" in root_card
    assert "1 x aws_foo_bar" in root_card and "1 x aws_lb" in root_card
    network_card = cards["modules.network"]
    assert "providers: aws 1, azurerm 1" in network_card
    legend = next(node for node in diagram.nodes if node.id == "tf_ov_legend")
    assert "2 module directories" in legend.label
    assert "Providers: aws 3, azurerm 1" in legend.label


def test_detail_renders_icons_and_internal_edges():
    diagram = build_terraform_module_detail_ir({}, _snapshot(), "")
    assert diagram is not None
    assert diagram.title == "Terraform infrastructure - root module"
    by_id = {node.id: node for node in diagram.nodes}
    container = by_id["tf_mod"]
    assert container.label == "root module"
    labels = {node.label for node in diagram.nodes if node.parent == "tf_mod"}
    assert "app\naws_lb" in labels
    assert "network\nmodule" in labels
    # the only internal uses edge: aws_lb.app -> module.network (var edge excluded)
    assert len(diagram.edges) == 1
    assert by_id[diagram.edges[0].source].label == "app\naws_lb"
    assert by_id[diagram.edges[0].target].label == "network\nmodule"
    legend = next(node for node in diagram.nodes if node.id == "tf_mod_legend")
    assert "Internal reference edges: 1" in legend.label


def test_detail_targets_apply_substance_threshold():
    # root module has 3 rendered blocks (threshold), modules.network only 2
    assert terraform_detail_packages(_snapshot()) == [""]


def test_tool_call_set_walks_overview_then_details():
    calls = build_terraform_diagram_tool_calls({}, _snapshot(), None)
    titles = [json.loads(call["function"]["arguments"])["title"] for call in calls]
    assert titles == [
        "Terraform infrastructure - Module overview",
        "Terraform infrastructure - root module",
    ]
    for call in calls:
        xml = json.loads(call["function"]["arguments"])["xml"]
        assert "<mxCell" in xml
        assert "QUALITY" not in xml  # no quality-gate violation stamp


def test_tool_call_set_is_deterministic():
    first = build_terraform_diagram_tool_calls({}, _snapshot(), None)
    second = build_terraform_diagram_tool_calls({}, _snapshot(), None)
    assert [call["function"]["arguments"] for call in first] == [
        call["function"]["arguments"] for call in second
    ]


def test_common_workspace_prefix_is_stripped_with_legend_note():
    snapshot = _snapshot()
    for node in snapshot["diagram_brief"]["selected_nodes"]:
        attributes = node.get("attributes") or {}
        if node["type"] == "package":
            node["label"] = "var.repos.x.terraform.modules.network"
        elif "package" in attributes:
            base = attributes["package"]
            attributes["package"] = f"var.repos.x.terraform.{base}" if base else "var.repos.x.terraform.base"
    diagram = build_terraform_module_overview_ir({}, snapshot)
    headers = [node.label.splitlines()[0] for node in diagram.nodes if node.id.startswith("tf_card")]
    assert any(header.startswith("base - ") for header in headers)
    assert any(header.startswith("modules.network - ") for header in headers)
    legend = next(node for node in diagram.nodes if node.id == "tf_ov_legend")
    assert "Module root (stripped from card labels): var.repos.x.terraform" in legend.label
    detail = build_terraform_module_detail_ir({}, snapshot, "var.repos.x.terraform.base")
    assert detail.title == "Terraform infrastructure - base"


def test_detail_hidden_blocks_surface_as_explicit_tail_under_gate():
    snapshot = _snapshot()
    extra = [
        _node(f"class:aws_sqs_queue.q{index}", "resource", f"aws_sqs_queue.q{index}", "", "aws_sqs_queue")
        for index in range(45)
    ]
    snapshot["diagram_brief"]["selected_nodes"].extend(extra)
    diagram = build_terraform_module_detail_ir({}, snapshot, "")
    tails = [node for node in diagram.nodes if node.id.endswith("_tail")]
    assert tails and "more blocks" in tails[0].label
    children_by_parent: dict[str, int] = {}
    for node in diagram.nodes:
        if node.parent != "1":
            children_by_parent[node.parent] = children_by_parent.get(node.parent, 0) + 1
    assert all(count <= 40 for count in children_by_parent.values())
    # the set stays gate-clean with the oversized module
    calls = build_terraform_diagram_tool_calls({}, snapshot, None)
    for call in calls:
        assert "QUALITY" not in json.loads(call["function"]["arguments"])["xml"]
