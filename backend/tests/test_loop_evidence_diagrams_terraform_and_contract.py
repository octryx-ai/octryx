"""A Terraform snapshot renders its dedicated diagram set once and then drops freehand calls."""

import json

from app.agent.loops.request._loop_evidence_diagrams import enforce_evidence_backed_diagrams
from tests.loop_evidence_diagrams_support import _freehand_call


def _terraform_snapshot():
    from tests.test_code_structure_terraform_view import _snapshot

    return _snapshot()


def test_terraform_snapshot_renders_dedicated_diagram_set():
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=[{"tool_name": "code_structure_snapshot", "result": _terraform_snapshot()}],
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    titles = [json.loads(call["function"]["arguments"])["title"] for call in calls]
    assert titles == [
        "Terraform infrastructure - Module overview",
        "Terraform infrastructure - root module",
    ]
    detail_xml = json.loads(calls[1]["function"]["arguments"])["xml"]
    assert "resIcon=mxgraph.aws4.application_load_balancer" in detail_xml
    assert trace["reason"] == "rendered_terraform_diagram_set"


def test_terraform_set_titles_are_walked_not_repeated():
    history = [
        {"tool_name": "code_structure_snapshot", "result": _terraform_snapshot()},
        {
            "tool_name": "create_diagram",
            "result": {
                "status": "created",
                "diagram_id": "d1",
                "title": "Terraform infrastructure - Module overview",
            },
        },
    ]
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=history,
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    titles = [json.loads(call["function"]["arguments"])["title"] for call in calls]
    # overview already rendered -> only the missing module detail remains
    assert titles == ["Terraform infrastructure - root module"]
    assert trace["reason"] == "rendered_terraform_diagram_set"


def test_terraform_complete_set_drops_further_freehand_calls():
    history = [
        {"tool_name": "code_structure_snapshot", "result": _terraform_snapshot()},
        {
            "tool_name": "create_diagram",
            "result": {
                "status": "created",
                "diagram_id": "d1",
                "title": "Terraform infrastructure - Module overview",
            },
        },
        {
            "tool_name": "create_diagram",
            "result": {
                "status": "created",
                "diagram_id": "d2",
                "title": "Terraform infrastructure - root module",
            },
        },
    ]
    enforced = enforce_evidence_backed_diagrams(
        tool_calls=[_freehand_call()],
        turn_tool_history=history,
        allowed_tool_names={"create_diagram"},
    )
    assert enforced is not None
    calls, trace = enforced
    assert calls == []
    assert trace["reason"] == "rendered_terraform_diagram_set"

