"""code_structure_snapshot: deterministic code evidence for source diagrams.

Covers the collector (literal declarations only) and the snapshot-driven class
diagram builder (members come from the snapshot, never from placeholders).
"""

import json

from app.services.diagrams.code_structure_diagrams import build_code_structure_class_diagram_tool_call
from app.tools.code_structure import collect_code_structure_snapshot
from tests.code_structure_snapshot_support import _fixture_workspace


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


# ── snapshot-driven builders ─────────────────────────────────────────────────


def _diagram_xml(snapshot):
    calls = build_code_structure_class_diagram_tool_call(snapshot, {"create_diagram"}, title="Test Diagram")
    assert len(calls) == 1
    return json.loads(calls[0]["function"]["arguments"])["xml"]


# ── collector ────────────────────────────────────────────────────────────────


def test_collector_reads_literal_declarations(tmp_path):
    snapshot = collect_code_structure_snapshot(_fixture_workspace(tmp_path), {})

    assert snapshot["service_summary"]["file_count"] == 4
    assert snapshot["service_summary"]["class_count"] == 4
    assert snapshot["service_summary"]["counts_by_language"] == {"java": 3, "python": 1}

    invoice = _node_by_ref(snapshot, "class:com.acme.billing.Invoice")
    assert invoice["type"] == "class"
    assert invoice["label"] == "Invoice"
    assert invoice["attributes"]["package"] == "com.acme.billing"
    assert invoice["attributes"]["fields"] == ["total: BigDecimal", "items: List<LineItem>"]
    assert invoice["attributes"]["methods"] == [
        "+Invoice(id)",
        "+computeTotal(policy): BigDecimal",
        "+addItem(item): void",
    ]

    python_model = _node_by_ref(snapshot, "class:billing.InvoiceModel")
    assert python_model["attributes"]["fields"] == ["amount: float", "currency"]
    assert python_model["attributes"]["methods"] == ["+to_dict(include_none)"]

    edges = _edge_set(snapshot)
    assert ("class:com.acme.billing.Invoice", "extends", "class:com.acme.core.Document") in edges
    assert ("class:com.acme.billing.Invoice", "uses", "class:com.acme.core.AuditLog") in edges
    assert ("class:com.acme.billing.Invoice", "belongs_to", "package:com.acme.billing") in edges
    assert ("class:com.acme.core.Document", "belongs_to", "package:com.acme.core") in edges
    # nothing invented: Payable is declared but not discovered -> no edge
    assert not any("Payable" in ref for _, _, ref in edges)


def test_collector_bounds_are_explicit_not_silent(tmp_path):
    workspace = _fixture_workspace(tmp_path)
    snapshot = collect_code_structure_snapshot(workspace, {"max_files": 2, "max_symbols": 1})

    assert snapshot["service_summary"]["file_count"] == 2
    assert snapshot["diagram_brief"]["truncated"] is True
    assert any("max_files" in warning for warning in snapshot["warnings"])


def test_collector_errors_on_missing_workspace(tmp_path):
    result = collect_code_structure_snapshot(tmp_path / "does-not-exist", {})
    assert "error" in result


def test_collector_errors_on_empty_workspace(tmp_path):
    # An empty workspace must be an explicit error, not a zero-node success:
    # a batched runtime otherwise treats the empty snapshot as evidence and
    # renders an invented diagram before the repository was fetched.
    result = collect_code_structure_snapshot(tmp_path, {})
    assert "error" in result
    assert "prepare_bitbucket_repository" in result["error"]


def test_collector_errors_when_language_filter_matches_nothing(tmp_path):
    result = collect_code_structure_snapshot(_fixture_workspace(tmp_path), {"languages": ["rust"]})
    assert "error" in result


def test_collector_language_filter(tmp_path):
    snapshot = collect_code_structure_snapshot(_fixture_workspace(tmp_path), {"languages": ["python"]})
    assert snapshot["service_summary"]["counts_by_language"] == {"python": 1}
    refs = {node["ref"] for node in snapshot["diagram_brief"]["selected_nodes"]}
    assert refs == {"class:billing.InvoiceModel", "package:billing"}


def test_uml_class_builder_renders_snapshot_members(tmp_path):
    snapshot = collect_code_structure_snapshot(_fixture_workspace(tmp_path), {})
    xml = _diagram_xml(snapshot)

    assert "Invoice" in xml
    assert "Document" in xml
    assert "total: BigDecimal" in xml
    assert "+computeTotal(policy): BigDecimal" in xml
    assert "extends" in xml
    # no hardcoded placeholder members
    assert "+authenticate()" not in xml
    assert "+isExpired()" not in xml
