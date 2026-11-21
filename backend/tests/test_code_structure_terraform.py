"""Terraform (HCL) parser: deterministic snapshot evidence from *.tf repos.

Covers the literal block mapping (resource/data/module/variable/output ->
typed nodes, directories -> package nodes), reference edges (TYPE.NAME,
module.X, var.Y, depends_on entries), provider classification from the
resource-type prefix, and the keys-only security policy (no argument value
ever enters the snapshot).
"""

import json

from app.tools.code_structure import collect_code_structure_snapshot

_ROOT_MAIN_TF = """\
# Root composition
module "network" {
  source     = "./modules/network"
  cidr_block = var.vpc_cidr
}

resource "aws_lb" "app" {
  name               = "app-alb"
  load_balancer_type = "application"
  subnets            = module.network.public_subnet_ids
  security_groups    = [aws_security_group.alb.id]

  access_logs {
    bucket = aws_s3_bucket.logs.id
  }

  depends_on = [aws_s3_bucket.logs]
}

resource "aws_security_group" "alb" {
  vpc_id = module.network.vpc_id
}

resource "aws_s3_bucket" "logs" {
  bucket = "app-access-logs"
}

resource "aws_rds_cluster" "main" {
  cluster_identifier = "app-db"
  master_username    = "admin"
  master_password    = "SuperSecretValue123!"  # must never enter the snapshot
  vpc_security_group_ids = [aws_security_group.alb.id]
  ami_hint = data.aws_ami.ubuntu.id
}

data "aws_ami" "ubuntu" {
  most_recent = true
}

variable "vpc_cidr" {
  type    = string
  default = "10.99.0.0/16"
}

output "alb_dns_name" {
  value = aws_lb.app.dns_name
}
"""

_NETWORK_VPC_TF = """\
resource "aws_vpc" "main" {
  cidr_block = var.cidr_block
}

resource "aws_subnet" "public" {
  vpc_id = aws_vpc.main.id
}

variable "cidr_block" {}
"""

_MULTICLOUD_TF = """\
resource "azurerm_linux_virtual_machine" "worker" {
  admin_password = "AzureHunter2!"
}

resource "google_compute_instance" "batch" {
  machine_type = "e2-small"
}

resource "vendorx_gadget" "one" {
  api_token = "vendor-token-value"
}
"""


def _fixture_workspace(tmp_path):
    (tmp_path / "main.tf").write_text(_ROOT_MAIN_TF)
    network = tmp_path / "modules" / "network"
    network.mkdir(parents=True)
    (network / "vpc.tf").write_text(_NETWORK_VPC_TF)
    (tmp_path / "multicloud").mkdir()
    (tmp_path / "multicloud" / "main.tf").write_text(_MULTICLOUD_TF)
    return tmp_path


def _node_by_ref(snapshot, ref):
    for node in snapshot["diagram_brief"]["selected_nodes"]:
        if node["ref"] == ref:
            return node
    raise AssertionError(f"node not found: {ref}")


def _edge_set(snapshot):
    return {
        (edge["source_ref"], edge["type"], edge["target_ref"])
        for edge in snapshot["diagram_brief"]["selected_edges"]
    }


def test_blocks_become_typed_nodes_with_package_dirs(tmp_path):
    snapshot = collect_code_structure_snapshot(_fixture_workspace(tmp_path), {"languages": ["terraform"]})

    assert snapshot["service_summary"]["counts_by_language"] == {"terraform": 3}

    alb = _node_by_ref(snapshot, "class:aws_lb.app")
    assert alb["type"] == "resource"
    assert alb["attributes"]["resource_type"] == "aws_lb"
    assert alb["attributes"]["provider"] == "aws"
    assert alb["attributes"]["file"] == "main.tf"

    module = _node_by_ref(snapshot, "class:module.network")
    assert module["type"] == "module"

    data_node = _node_by_ref(snapshot, "class:data.aws_ami.ubuntu")
    assert data_node["type"] == "data"
    assert data_node["attributes"]["resource_type"] == "aws_ami"

    assert _node_by_ref(snapshot, "class:var.vpc_cidr")["type"] == "variable"
    assert _node_by_ref(snapshot, "class:output.alb_dns_name")["type"] == "output"

    vpc = _node_by_ref(snapshot, "class:modules.network.aws_vpc.main")
    assert vpc["type"] == "resource"
    assert _node_by_ref(snapshot, "package:modules.network")["type"] == "package"


def test_reference_edges_from_literal_addresses(tmp_path):
    snapshot = collect_code_structure_snapshot(
        _fixture_workspace(tmp_path), {"languages": ["terraform"], "max_symbols": 100}
    )
    edges = _edge_set(snapshot)

    # attribute references
    assert ("class:aws_lb.app", "uses", "class:aws_security_group.alb") in edges
    assert ("class:aws_lb.app", "uses", "class:module.network") in edges
    # depends_on entries use the same literal address grammar
    assert ("class:aws_lb.app", "uses", "class:aws_s3_bucket.logs") in edges
    # var.X and data.TYPE.NAME references
    assert ("class:module.network", "uses", "class:var.vpc_cidr") in edges
    assert ("class:aws_rds_cluster.main", "uses", "class:data.aws_ami.ubuntu") in edges
    # cross-directory reference resolves to the module directory's node
    assert (
        "class:modules.network.aws_subnet.public",
        "uses",
        "class:modules.network.aws_vpc.main",
    ) in edges
    # containment
    assert ("class:modules.network.aws_vpc.main", "belongs_to", "package:modules.network") in edges


def test_provider_prefix_classification(tmp_path):
    snapshot = collect_code_structure_snapshot(
        _fixture_workspace(tmp_path), {"languages": ["terraform"], "max_symbols": 100}
    )
    azure = _node_by_ref(snapshot, "class:multicloud.azurerm_linux_virtual_machine.worker")
    assert azure["attributes"]["provider"] == "azurerm"
    google = _node_by_ref(snapshot, "class:multicloud.google_compute_instance.batch")
    assert google["attributes"]["provider"] == "google"
    vendor = _node_by_ref(snapshot, "class:multicloud.vendorx_gadget.one")
    assert vendor["attributes"]["provider"] == "other"


def test_fields_are_key_names_only_and_values_never_leak(tmp_path):
    snapshot = collect_code_structure_snapshot(
        _fixture_workspace(tmp_path), {"languages": ["terraform"], "max_symbols": 100}
    )

    rds = _node_by_ref(snapshot, "class:aws_rds_cluster.main")
    assert "master_password" in rds["attributes"]["fields"]
    assert "cluster_identifier" in rds["attributes"]["fields"]

    serialized = json.dumps(snapshot)
    # argument VALUES (secrets, CIDRs, tokens, names) never enter the snapshot
    assert "SuperSecretValue123" not in serialized
    assert "AzureHunter2" not in serialized
    assert "vendor-token-value" not in serialized
    assert "10.99.0.0/16" not in serialized
    assert "app-access-logs" not in serialized


def test_module_quota_keeps_weakly_wired_modules_in_the_brief(tmp_path):
    # hub: 5 heavily wired blocks; leaf: 2 blocks with zero references.
    # A global degree-first cut at max_symbols=5 would drop `leaf` entirely;
    # the terraform module quota must keep every directory represented.
    hub = tmp_path / "hub"
    hub.mkdir()
    hub_blocks = []
    for index in range(5):
        target = f"aws_s3_bucket.b{(index + 1) % 5}"
        hub_blocks.append(
            f'resource "aws_s3_bucket" "b{index}" {{\n  a = {target}.id\n  b = aws_s3_bucket.b{(index + 2) % 5}.id\n}}\n'
        )
    (hub / "main.tf").write_text("\n".join(hub_blocks))
    leaf = tmp_path / "leaf"
    leaf.mkdir()
    (leaf / "main.tf").write_text(
        'resource "aws_sqs_queue" "q1" {\n  name_key = "x"\n}\n\n'
        'resource "aws_sqs_queue" "q2" {\n  name_key = "y"\n}\n'
    )

    snapshot = collect_code_structure_snapshot(tmp_path, {"languages": ["terraform"], "max_symbols": 5})
    selected = {
        node["ref"]
        for node in snapshot["diagram_brief"]["selected_nodes"]
        if node["type"] != "package"
    }
    assert any(ref.startswith("class:leaf.") for ref in selected), selected
    assert any(ref.startswith("class:hub.") for ref in selected)

    packages = {
        node["label"]: node["attributes"]
        for node in snapshot["diagram_brief"]["selected_nodes"]
        if node["type"] == "package"
    }
    # explicit per-module counters: totals and the selected sample size
    assert packages["hub"]["class_count"] == 5
    assert packages["hub"]["selected_count"] == 3
    assert packages["leaf"]["class_count"] == 2
    assert packages["leaf"]["selected_count"] == 2
    assert any("package hub: 3 of 5 blocks selected" in warning for warning in snapshot["warnings"])


def test_snapshot_is_deterministic(tmp_path):
    workspace = _fixture_workspace(tmp_path)
    first = collect_code_structure_snapshot(workspace, {"languages": ["terraform"], "max_symbols": 100})
    second = collect_code_structure_snapshot(workspace, {"languages": ["terraform"], "max_symbols": 100})
    first.pop("generated_at", None)
    second.pop("generated_at", None)
    assert first == second
