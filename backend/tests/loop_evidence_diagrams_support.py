"""Shared helpers for the test_loop_evidence_diagrams_* modules."""

import json


def _freehand_call(name="create_diagram"):
    return {
        "id": "call_1",
        "function": {"name": name, "arguments": json.dumps({"title": "My own", "xml": "<mxCell/>"})},
    }


def _names(calls):
    return [str((c.get("function") or {}).get("name")) for c in calls]
