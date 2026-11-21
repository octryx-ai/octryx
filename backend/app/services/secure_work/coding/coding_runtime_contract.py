from __future__ import annotations

from typing import Any

CODING_RUNTIME_CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "id": "state_machine_completion_contract",
        "owner": "secure_work.coding_state_machine",
        "purpose": "Coding work can only complete from explicit runtime evidence, not from assistant prose.",
        "config_surface": "coding pipeline definition and Work Change Plan approval",
        "audit_event": "work_coding_audit_events.agent_execution_started",
    },
    {
        "id": "progress_quality_completion_evidence",
        "owner": "agent.loops.progress_quality",
        "purpose": (
            "No-tool implementation, validation, or completion claims require matching tool evidence or a blocker."
        ),
        "config_surface": "runtime settings stuck-loop thresholds",
        "audit_event": "turn_trace.raw_output.progress_quality_event",
    },
    {
        "id": "duplicate_read_only_reuse",
        "owner": "agent.core.turn.turn_tools",
        "purpose": "Exact repeated read-only tool calls reuse prior evidence instead of spending another tool turn.",
        "config_surface": "runtime tool history",
        "audit_event": "tool_call.result.progress_quality_event",
    },
    {
        "id": "workspace_mutation_policy",
        "owner": "secure_work.coding_policy_runtime",
        "purpose": "Admin-managed coding policies can allow, warn, require review, or block workspace mutations.",
        "config_surface": "Coding governance policies UI/API",
        "audit_event": "tool_call.result.coding_policy_decision",
    },
    {
        "id": "validation_outcome_contract",
        "owner": "services.coding_validation",
        "purpose": "Validation commands expose passed, failed, missing-tool, timeout, and wrong-cwd outcomes.",
        "config_surface": "Work Plan validation commands and execution runtime configuration",
        "audit_event": "tool_call.result.validation_outcome",
    },
)


def coding_runtime_control_inventory() -> list[dict[str, Any]]:
    return [dict(control) for control in CODING_RUNTIME_CONTROLS]


def coding_execution_contract(state_machine: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(state_machine or {})
    next_action = dict(state.get("next_action") or {})
    return {
        "version": "coding_execution_contract.v1",
        "completion_source": "runtime_state_machine",
        "completion_allowed_when": [
            "pull_request_recorded",
            "explicit_noop_evidence",
            "explicit_blocker_recorded",
        ],
        "next_required_action": str(next_action.get("key") or "unknown"),
        "required_evidence": [str(item) for item in state.get("required_evidence") or []],
        "control_ids": [str(control["id"]) for control in CODING_RUNTIME_CONTROLS],
    }


def coding_execution_contract_prompt_lines(contract: dict[str, Any]) -> list[str]:
    allowed = ", ".join(str(item) for item in contract.get("completion_allowed_when") or [])
    required = ", ".join(str(item) for item in contract.get("required_evidence") or []) or "state-machine evidence"
    controls = ", ".join(str(item) for item in contract.get("control_ids") or [])
    return [
        "Runtime execution contract:",
        f"- contract_version: {contract.get('version') or 'unknown'}",
        f"- completion_source: {contract.get('completion_source') or 'runtime_state_machine'}",
        f"- completion_allowed_when: {allowed}",
        f"- next_required_action: {contract.get('next_required_action') or 'unknown'}",
        f"- required_evidence: {required}",
        f"- active_controls: {controls}",
    ]
