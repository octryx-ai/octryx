"""Binding evidence-backed diagram rule: freehand create_diagram never
dispatches once the turn holds an aws_topology_snapshot (or a
code_structure_snapshot for source-code diagrams)."""

import json

from app.agent.loops.request._loop_evidence_diagrams import enforce_evidence_backed_diagrams
from tests.aws_topology_structural_layout_support import _shape_library, _topology_result
from tests.loop_evidence_diagrams_support import _freehand_call, _names


def _code_structure_snapshot():
    return {
        "workspace": "/tmp/workspace",
        "service_summary": {"file_count": 2, "class_count": 2, "package_count": 1},
        "diagram_brief": {
            "selected_nodes": [
                {
                    "ref": "class:com.acme.core.Document",
                    "type": "class",
                    "label": "Document",
                    "attributes": {
                        "package": "com.acme.core",
                        "file": "Document.java",
                        "fields": ["id: UUID"],
                        "methods": ["+getId(): UUID"],
                    },
                },
                {
                    "ref": "class:com.acme.core.Invoice",
                    "type": "class",
                    "label": "Invoice",
                    "attributes": {
                        "package": "com.acme.core",
                        "file": "Invoice.java",
                        "fields": ["total: BigDecimal"],
                        "methods": ["+computeTotal(): BigDecimal"],
                    },
                },
            ],
            "selected_edges": [
                {
                    "source_ref": "class:com.acme.core.Invoice",
                    "target_ref": "class:com.acme.core.Document",
                    "type": "extends",
                }
            ],
            "truncated": False,
        },
        "warnings": [],
    }


def _history(*, with_snapshot=True, with_library=True, diagram_count=0, titles=()):
    history = []
    if with_snapshot:
        history.append({"tool_name": "aws_topology_snapshot", "result": _topology_result()})
    if with_library:
        history.append({"tool_name": "get_shape_library", "result": _shape_library()})
    rendered = list(titles) or [f"diagram-{index}" for index in range(diagram_count)]
    if diagram_count and titles:
        rendered = list(titles)
    for index, title in enumerate(rendered if (diagram_count or titles) else []):
        history.append(
            {"tool_name": "create_diagram", "result": {"status": "created", "diagram_id": f"d{index}", "title": title}}
        )
    return history


def test_freehand_diagram_is_replaced_by_deterministic_overview():
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=_history(),
        allowed_tool_names={"create_diagram", "get_shape_library"},
    )
    assert enforced is not None
    calls, trace = enforced
    assert _names(calls) == ["create_diagram"]
    args = json.loads(calls[0]["function"]["arguments"])
    # deterministic renderer output, not the model's XML
    assert args["title"] == "AWS Topology Overview"
    assert "aws_cloud" in args["xml"]
    assert trace["rule"] == "evidence_backed_diagrams"
    assert trace["reason"] == "rendered_evidence_overview"


def test_after_first_diagram_freehand_is_replaced_by_detail_set():
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=_history(diagram_count=1),
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    titles = [json.loads(c["function"]["arguments"])["title"] for c in calls]
    assert titles and titles[0] == "AWS Topology - Service inventory"
    assert trace["reason"] == "rendered_evidence_details"


def test_already_rendered_sections_are_not_repeated():
    # inventory exists -> next replacement is the FIRST MISSING section
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=_history(titles=("AWS Topology Overview", "AWS Topology - Service inventory")),
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, _trace_info = enforced
    titles = [json.loads(c["function"]["arguments"])["title"] for c in calls]
    assert "AWS Topology - Service inventory" not in titles
    assert titles, "expected the missing detail sections"


def test_missing_shape_library_requests_it_deterministically():
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=_history(with_library=False),
        allowed_tool_names={"create_diagram", "get_shape_library"},
    )
    assert enforced is not None
    calls, trace = enforced
    assert _names(calls) == ["get_shape_library"]
    assert trace["reason"] == "requested_shape_library"


def test_no_snapshot_means_no_interference():
    assert (
        enforce_evidence_backed_diagrams(
            tool_calls=[_freehand_call()],
            turn_tool_history=_history(with_snapshot=False),
            allowed_tool_names={"create_diagram"},
        )
        is None
    )


def test_non_diagram_calls_pass_through_untouched():
    other = {"id": "c2", "function": {"name": "aws_topology_snapshot", "arguments": "{}"}}
    assert (
        enforce_evidence_backed_diagrams(
            tool_calls=[other],
            turn_tool_history=_history(),
            allowed_tool_names={"create_diagram"},
        )
        is None
    )


def test_freehand_is_replaced_by_code_structure_class_diagram():
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=[{"tool_name": "code_structure_snapshot", "result": _code_structure_snapshot()}],
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    assert _names(calls) == ["create_diagram"]
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["title"] == "Code structure - Class diagram"
    assert "Invoice" in args["xml"]
    assert "total: BigDecimal" in args["xml"]
    assert "extends" in args["xml"]
    assert trace["rule"] == "evidence_backed_diagrams"
    assert trace["reason"] == "rendered_code_structure_class_diagram"


def test_aws_snapshot_takes_precedence_over_code_structure_snapshot():
    history = _history() + [{"tool_name": "code_structure_snapshot", "result": _code_structure_snapshot()}]
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=history,
        allowed_tool_names={"create_diagram", "get_shape_library"},
    )
    assert enforced is not None
    calls, trace = enforced
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["title"] == "AWS Topology Overview"
    assert trace["reason"] == "rendered_evidence_overview"


def test_code_structure_class_diagram_is_not_repeated():
    history = [
        {"tool_name": "code_structure_snapshot", "result": _code_structure_snapshot()},
        {
            "tool_name": "create_diagram",
            "result": {"status": "created", "diagram_id": "d1", "title": "Code structure - Class diagram"},
        },
    ]
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=history,
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    # freehand stays dropped, nothing new is rendered
    assert calls == []
    assert trace["reason"] == "rendered_code_structure_class_diagram"


def test_code_snapshot_without_classes_means_no_interference():
    empty_snapshot = {"diagram_brief": {"selected_nodes": [], "selected_edges": [], "truncated": False}}
    assert (
        enforce_evidence_backed_diagrams(
            tool_calls=[_freehand_call()],
            turn_tool_history=[{"tool_name": "code_structure_snapshot", "result": empty_snapshot}],
            allowed_tool_names={"create_diagram"},
        )
        is None
    )
