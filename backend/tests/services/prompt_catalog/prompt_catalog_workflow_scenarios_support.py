"""Fixed inputs for the workflow prompt scenario golden (``test_prompt_catalog_workflow_scenarios.py``)."""

from __future__ import annotations

from typing import Any

from app.services.workflow_routing.model_catalog import render_model_workflow_catalog_prompt


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
    return {f"catalog:{name}": render_model_workflow_catalog_prompt(value) for name, value in _catalogs().items()}
