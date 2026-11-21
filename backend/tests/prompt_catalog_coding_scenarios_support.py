"""Fixed inputs for the coding prompt scenarios (``test_prompt_catalog_coding_scenarios.py``).

Each scenario calls a public builder of the catalog-backed coding call sites (TDD cycle
reminders, coding workflow agent definitions) with fixed inputs. The digests in ``prompt_catalog_golden_keys_coding.SCENARIOS``
are the pinned outputs of the same builders.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from app.agent.core.guards.tdd_cycle import (
    augment_step_with_tdd_cycle,
    build_initial_tdd_cycle_state,
    build_tdd_cycle_incomplete_reminder,
    build_tdd_cycle_progress_message,
    record_tdd_cycle_tool_result,
    resolve_tdd_cycle_phases,
)
from app.services.workflow_contracts.agent_definition import build_workflow_agent_definition

STEP = {"name": "Implement And Verify Change"}
CUSTOM_STEP = {
    "name": "Custom",
    "stepConfig": {
        "tdd_cycle_phases": [
            "write_tests",
            {"name": "refactor", "instructions": "Custom refactor wording."},
            "security_review",
            {"name": "check", "title": "Check", "instructions": "Check it.", "required_tools": []},
        ]
    },
}


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _tdd() -> dict[str, str]:
    outputs: dict[str, str] = {}
    for label, step in (("default", STEP), ("custom", CUSTOM_STEP)):
        state = build_initial_tdd_cycle_state(step)
        outputs[f"tdd:phases:{label}"] = _dump(resolve_tdd_cycle_phases(step))
        for index in range(len(state["phases"])):
            state["phase_index"] = index
            outputs[f"tdd:reminder:{label}:{index}"] = build_tdd_cycle_incomplete_reminder(step, state)
            outputs[f"tdd:progress:{label}:{index}"] = build_tdd_cycle_progress_message(state)
            outputs[f"tdd:augment:{label}:{index}"] = _dump(augment_step_with_tdd_cycle(step, state))
    single = {"name": "One", "stepConfig": {"tdd_cycle_phases": ["write_tests"]}}
    state = build_initial_tdd_cycle_state(single)
    record_tdd_cycle_tool_result(state, "run_test_suite", {"all_green": False})
    outputs["tdd:progress:complete"] = build_tdd_cycle_progress_message(state)
    outputs["tdd:reminder:no_phases"] = build_tdd_cycle_incomplete_reminder({}, {})
    return outputs


CONTRACTS: dict[str, dict[str, Any]] = {
    "coding:tdd": {"workflow_id": "coding_change_tdd", "topic": "Fix the parser"},
    "coding:contract": {
        "workflow_id": "coding_change_tdd",
        "topic": "Cleanup",
        "verification_contract": {"commands": [{"command": "terraform validate"}, {"command": "make test"}]},
        "delivery": {"source_control_provider": "bitbucket", "ticket_provider": "jira"},
    },
}


def _agent_definitions() -> dict[str, str]:
    return {f"agent:{name}": _dump(build_workflow_agent_definition(contract)) for name, contract in CONTRACTS.items()}


def coding_scenario_outputs() -> dict[str, str]:
    return {**_tdd(), **_agent_definitions()}


def coding_scenario_digests() -> dict[str, str]:
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in coding_scenario_outputs().items()}
