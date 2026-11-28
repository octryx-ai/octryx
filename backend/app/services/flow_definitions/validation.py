"""Validation of a workflow definition: a phased graph or a fragment, each by its own validator; the flow graph
runtime (schema 2.0) was removed, so any other definition is refused."""

from __future__ import annotations

from typing import Any


def validate_flow_definition(definition: dict[str, Any]) -> dict[str, Any]:
    from ..workflow_runs.fragments.store import is_fragment
    from ..workflow_runs.graph import is_phased_definition
    from ..workflow_runs.graph_validation import validate_phased_definition

    if is_fragment(definition):
        # A fragment is validated inside its harness graph by the same phased validator.
        from ..workflow_runs.fragments.validation import validate_fragment_definition

        return validate_fragment_definition(definition)
    if is_phased_definition(definition):
        return validate_phased_definition(definition)
    return {"valid": False, "warnings": [], "errors": [{
        "code": "not_a_phased_workflow",
        "message": "Only workflows that run in phases exist; set execution_kind to \"phased\".",
    }]}
