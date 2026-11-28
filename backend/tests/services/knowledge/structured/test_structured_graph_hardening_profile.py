"""INI continuation, ticket node types and inventory patterns come from the generic profile, and the structured code names no product, cluster flavour or ticket project."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from app.services.knowledge.structured import build as build_module
from app.services.knowledge.structured.config_files import parse_ini
from app.services.knowledge.structured.ops_records import extract_inventory, extract_servicenow
from app.services.knowledge.structured.profile import PROFILE_PATH, load_profile, structured_profile
from app.services.knowledge.structured.profile_types import StructuredProfileError
from tests.services.knowledge.structured.test_structured_graph_operations import CITE, INVENTORY, JIRA

STRUCTURED = Path(build_module.__file__).parent


# --- Generic profile ----------------------------------------------------------------------------------


def test_ini_continuation_comes_from_the_profile():
    text = "[Db]\nSqlSelect = SELECT ID\n+ FROM T\n& WHERE X\n"
    assert structured_profile().continuation_prefixes == ("+",)
    plus = parse_ini(text, (";",), ("+",))
    assert plus.entries[0].value == "SELECT ID FROM T" and plus.skipped_lines == 1
    none = parse_ini(text, (";",), ())
    assert none.entries[0].value == "SELECT ID" and none.skipped_lines == 2
    ampersand = parse_ini("[Db]\nSqlSelect = SELECT ID\n& WHERE X\n", (";",), ("&",))
    assert ampersand.entries[0].value == "SELECT ID WHERE X"


def test_servicenow_node_types_are_the_profile_ticket_pattern_keys():
    request = "# RITM0001234: Access\n\n- Table: sc_req_item\n"
    profile = structured_profile()
    assert extract_servicenow(request, CITE, profile, JIRA).warnings == {"record_shape_unknown": 1}
    extended = dataclasses.replace(
        profile, ticket_patterns=profile.ticket_patterns + (("Request", re.compile(r"\bRITM[0-9]{7}\b")),)
    )
    (node,) = extract_servicenow(request, CITE, extended, JIRA).nodes
    assert node.node_type == "Request" and node.node_key == "servicenow:RITM0001234"


def test_inventory_patterns_come_from_the_profile_for_any_cluster_flavour():
    profile = structured_profile()
    aks = INVENTORY.replace("Cluster: EKS demo-nonprod-eks", "Cluster: AKS shop-prod")
    clusters = {fact.label for ref, fact in extract_inventory(aks, CITE, profile).nodes.items()
                if ref.node_type == "Cluster"}
    assert clusters == {"shop-prod"}
    custom = dataclasses.replace(
        profile,
        inventory_namespace_pattern=re.compile(r"\A# Inventar: Namespace (?P<namespace>[a-z0-9-]+)"),
        inventory_cluster_pattern=re.compile(r"(?m)^Kluster: (?P<cluster>[a-z0-9-]+)"),
    )
    german = "# Inventar: Namespace shop\n\nKluster: eu-one\n"
    names = {(ref.node_type, fact.label) for ref, fact in extract_inventory(german, CITE, custom).nodes.items()}
    assert names == {("Cluster", "eu-one"), ("Namespace", "shop")}


def test_a_profile_inventory_pattern_without_its_named_group_is_refused(tmp_path):
    raw = PROFILE_PATH.read_text(encoding="utf-8").replace("(?P<cluster>", "(?P<other>")
    broken = tmp_path / "structured.json"
    broken.write_text(raw, encoding="utf-8")
    with pytest.raises(StructuredProfileError, match="inventory_cluster_pattern"):
        load_profile(broken)


def test_the_structured_code_names_no_product_cluster_flavour_or_ticket_project():
    for path in sorted(STRUCTURED.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for word in ("Acme Orders", "ACME", "EKS"):
            assert word not in text, f"{path.name} names {word}"
