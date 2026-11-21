"""Fixed inputs for the workflow prompt scenario golden (``test_prompt_catalog_workflow_scenarios.py``).

Every branch of ``build_workflow_contract_message`` and the variants of
``render_model_workflow_catalog_prompt`` with fixed inputs. The golden module pins the SHA-256 of
each output as the code produced it before the texts moved into the prompt catalog;
``scenario_outputs`` is the one builder used to pin and to check.
"""

from __future__ import annotations

from typing import Any

from app.services.workflow_contracts.contract_message import build_workflow_contract_message
from app.services.workflow_routing.model_catalog import render_model_workflow_catalog_prompt

PHASES = [{"id": "gather"}, {"id": "build"}, {"id": ""}]
AXES = {"required_axes": ["security", "cost"]}


def _contracts() -> dict[str, dict[str, Any]]:
    base = {"topic": "Payments", "phases": PHASES, "evidence_contract": AXES}
    return {
        "empty": {},
        "coding": {**base, "workflow_id": "coding_change_tdd"},
        "coding_bare": {"workflow_id": "coding_change_tdd"},
        "knowledge_lookup": {**base, "workflow_id": "knowledge_request"},
    }


def _catalogs() -> dict[str, list[dict[str, Any]]]:
    return {
        "catalog_empty": [{"workflow_key": " "}],
        "catalog": [
            {"workflow_key": "coding-change-tdd", "capability": "change", "when_to_use": "Code change with tests."},
            {"workflow_key": "knowledge", "title": "Knowledge lookup"},
            {"workflow_key": "bare"},
        ],
    }


def scenario_outputs() -> dict[str, str]:
    outputs = {f"contract:{name}": build_workflow_contract_message(value) for name, value in _contracts().items()}
    outputs.update({f"catalog:{name}": render_model_workflow_catalog_prompt(value) for name, value in _catalogs().items()})
    return outputs
