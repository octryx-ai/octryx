"""Helpers for structured and configurable TDD cycle agent steps."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ....services.prompt_catalog import render_prompt
from .response_guards import get_step_field

# Phase structure lives in code; each phase's instructions are the catalog key
# ``coding.tdd.phase.<name>`` and are rendered when a phase is resolved (never at import).
DEFAULT_TDD_PHASES: list[dict[str, Any]] = [
    {
        "name": "write_tests",
        "title": "Write Tests",
        "completion_rule": "tool_called",
        "required_tools": ["run_test_suite"],
    },
    {
        "name": "make_green",
        "title": "Make Green",
        "completion_rule": "test_green",
        "required_tools": ["run_test_suite"],
    },
    {
        "name": "refactor",
        "title": "Refactor and Lint",
        "completion_rule": "lint_clean",
        "required_tools": ["lint_and_format_workspace"],
    },
    {
        "name": "self_review",
        "title": "Self Review",
        "completion_rule": "review_ready",
        "required_tools": ["self_review_workspace_diff", "build_pull_request_description"],
    },
]

PHASE_TEMPLATES: dict[str, dict[str, Any]] = {phase["name"]: deepcopy(phase) for phase in DEFAULT_TDD_PHASES}
PHASE_TEMPLATES["security_review"] = {
    "name": "security_review",
    "title": "Security Review",
    "completion_rule": "sast_clean",
    "required_tools": ["run_sast_suite"],
}


def _phase_template(name: str, *, with_instructions: bool = True) -> dict[str, Any]:
    """A copy of the named phase template with its catalog instructions, or ``{}`` when unknown."""
    template = deepcopy(PHASE_TEMPLATES.get(name, {}))
    if template and with_instructions:
        template["instructions"] = render_prompt(f"coding.tdd.phase.{name}")
    return template


def _default_phases() -> list[dict[str, Any]]:
    return [_phase_template(phase["name"]) for phase in DEFAULT_TDD_PHASES]


def is_tdd_cycle_step(step: dict[str, Any] | None) -> bool:
    return str(get_step_field(step, "stepType", "step_type", "") or "").strip().lower() == "tdd_cycle"


def _normalize_required_tools(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def resolve_tdd_cycle_phases(step: dict[str, Any] | None) -> list[dict[str, Any]]:
    step_config = (step or {}).get("stepConfig") if isinstance(step, dict) else None
    raw_phases = step_config.get("tdd_cycle_phases") if isinstance(step_config, dict) else None
    if not isinstance(raw_phases, list) or not raw_phases:
        return _default_phases()

    phases: list[dict[str, Any]] = []
    for index, raw_phase in enumerate(raw_phases):
        template: dict[str, Any] = {}
        if isinstance(raw_phase, str):
            template = _phase_template(raw_phase.strip())
        elif isinstance(raw_phase, dict):
            template_name = str(raw_phase.get("name") or "").strip()
            # Step-config fields (explicit instructions included) win over the catalog text.
            template = _phase_template(
                template_name, with_instructions=raw_phase.get("instructions") is None
            )
            template.update({key: value for key, value in raw_phase.items() if value is not None})
        if not template:
            continue
        phase_name = str(template.get("name") or f"phase_{index + 1}").strip() or f"phase_{index + 1}"
        template["name"] = phase_name
        template["title"] = str(template.get("title") or phase_name.replace("_", " ").title()).strip()
        template["instructions"] = str(template.get("instructions") or "").strip()
        completion_rule = str(template.get("completion_rule") or "tool_called").strip().lower()
        if completion_rule not in {"tool_called", "test_green", "lint_clean", "review_ready", "sast_clean", "validation_green"}:
            completion_rule = "tool_called"
        template["completion_rule"] = completion_rule
        template["required_tools"] = _normalize_required_tools(template.get("required_tools"))
        phases.append(template)
    return phases or _default_phases()


def build_initial_tdd_cycle_state(step: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "phase_index": 0,
        "phases": resolve_tdd_cycle_phases(step),
        "phase_tool_counts": {},
        "phase_results": {},
        "history": [],
    }


def restore_tdd_cycle_state(
    state: dict[str, Any] | None,
    *,
    step: dict[str, Any] | None,
) -> dict[str, Any]:
    restored = dict(state or {})
    restored["phase_index"] = int(restored.get("phase_index") or 0)
    restored["phase_tool_counts"] = dict(restored.get("phase_tool_counts") or {})
    restored["phase_results"] = dict(restored.get("phase_results") or {})
    restored["history"] = list(restored.get("history") or [])
    restored["phases"] = resolve_tdd_cycle_phases(step)
    max_index = max(0, len(restored["phases"]) - 1)
    restored["phase_index"] = max(0, min(restored["phase_index"], max_index))
    return restored


def export_tdd_cycle_state(state: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "phase_index": int((state or {}).get("phase_index") or 0),
        "phases": deepcopy(list((state or {}).get("phases") or [])),
        "phase_tool_counts": deepcopy(dict((state or {}).get("phase_tool_counts") or {})),
        "phase_results": deepcopy(dict((state or {}).get("phase_results") or {})),
        "history": deepcopy(list((state or {}).get("history") or [])),
    }


def current_tdd_cycle_phase(state: dict[str, Any] | None) -> dict[str, Any]:
    phases = list((state or {}).get("phases") or _default_phases())
    phase_index = int((state or {}).get("phase_index") or 0)
    if phase_index < 0:
        phase_index = 0
    if phase_index >= len(phases):
        phase_index = len(phases) - 1
    return phases[phase_index]


def augment_step_with_tdd_cycle(step: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any]:
    phase = current_tdd_cycle_phase(state)
    phase_index = int((state or {}).get("phase_index") or 0)
    phase_total = len(list((state or {}).get("phases") or DEFAULT_TDD_PHASES))
    step_copy = dict(step)
    step_copy["tddCyclePhase"] = phase["name"]
    step_copy["tddCyclePhaseTitle"] = phase["title"]
    step_copy["tddCyclePhaseIndex"] = phase_index + 1
    step_copy["tddCyclePhaseTotal"] = phase_total
    step_copy["tddCyclePhaseInstructions"] = phase["instructions"]
    step_copy["tddCyclePhaseRequiredTools"] = list(phase.get("required_tools") or [])
    step_copy["tddCycleCompletionRule"] = str(phase.get("completion_rule") or "tool_called")
    step_copy["tddCycleHistory"] = deepcopy(list((state or {}).get("history") or []))
    return step_copy


def record_tdd_cycle_tool_result(state: dict[str, Any], tool_name: str, result: dict[str, Any] | None) -> None:
    phase = current_tdd_cycle_phase(state)
    phase_name = str(phase["name"])
    tool_counts = state.setdefault("phase_tool_counts", {})
    result_store = state.setdefault("phase_results", {})
    history = state.setdefault("history", [])

    phase_counts = tool_counts.setdefault(phase_name, {})
    phase_counts[tool_name] = int(phase_counts.get(tool_name) or 0) + 1

    phase_results = result_store.setdefault(phase_name, {})
    phase_results[tool_name] = result or {}
    history.append({"phase": phase_name, "tool_name": tool_name, "result": result or {}})


def _tool_called_in_phase(state: dict[str, Any], phase_name: str, tool_name: str) -> bool:
    counts = (state.get("phase_tool_counts") or {}).get(phase_name) or {}
    return int(counts.get(tool_name) or 0) > 0


def _phase_result(state: dict[str, Any], phase_name: str, tool_name: str) -> dict[str, Any]:
    return ((state.get("phase_results") or {}).get(phase_name) or {}).get(tool_name) or {}


def is_tdd_cycle_phase_complete(state: dict[str, Any]) -> bool:
    phase = current_tdd_cycle_phase(state)
    phase_name = str(phase["name"])
    completion_rule = str(phase.get("completion_rule") or "tool_called").strip().lower()
    required_tools = _normalize_required_tools(phase.get("required_tools"))

    if completion_rule == "tool_called":
        return all(_tool_called_in_phase(state, phase_name, tool_name) for tool_name in required_tools)
    if completion_rule == "test_green":
        if not _tool_called_in_phase(state, phase_name, "run_test_suite"):
            return False
        test_result = _phase_result(state, phase_name, "run_test_suite")
        return not test_result.get("error") and bool(test_result.get("all_green"))
    if completion_rule == "validation_green":
        # Approved verification contract: the phase completes only when
        # run_validation_commands reports all_green — the exact per-run gate.
        if not _tool_called_in_phase(state, phase_name, "run_validation_commands"):
            return False
        validation_result = _phase_result(state, phase_name, "run_validation_commands")
        return not validation_result.get("error") and bool(validation_result.get("all_green"))
    if completion_rule == "lint_clean":
        if not _tool_called_in_phase(state, phase_name, "lint_and_format_workspace"):
            return False
        lint_result = _phase_result(state, phase_name, "lint_and_format_workspace")
        return not lint_result.get("error") and bool(lint_result.get("all_clean"))
    if completion_rule == "review_ready":
        if not _tool_called_in_phase(state, phase_name, "self_review_workspace_diff"):
            return False
        if not _tool_called_in_phase(state, phase_name, "build_pull_request_description"):
            return False
        review_result = _phase_result(state, phase_name, "self_review_workspace_diff")
        return not review_result.get("error") and bool(review_result.get("ready_for_pr"))
    if completion_rule == "sast_clean":
        if not _tool_called_in_phase(state, phase_name, "run_sast_suite"):
            return False
        sast_result = _phase_result(state, phase_name, "run_sast_suite")
        return not sast_result.get("error") and bool(sast_result.get("all_clean"))
    return False


def is_tdd_cycle_complete(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    phase_index = int(state.get("phase_index") or 0)
    phases = list(state.get("phases") or DEFAULT_TDD_PHASES)
    return phase_index >= len(phases) - 1 and is_tdd_cycle_phase_complete(state)


def advance_tdd_cycle_phase(state: dict[str, Any]) -> bool:
    if not is_tdd_cycle_phase_complete(state):
        return False
    phases = list(state.get("phases") or DEFAULT_TDD_PHASES)
    phase_index = int(state.get("phase_index") or 0)
    if phase_index >= len(phases) - 1:
        return False
    state["phase_index"] = phase_index + 1
    return True


def _phase_total(state: dict[str, Any]) -> int:
    return len(list(state.get("phases") or DEFAULT_TDD_PHASES))


def build_tdd_cycle_incomplete_reminder(step: dict[str, Any], state: dict[str, Any]) -> str:
    phase = current_tdd_cycle_phase(state)
    required_tools = _normalize_required_tools(phase.get("required_tools"))
    tools_suffix = (
        render_prompt("coding.tdd.required_tools_suffix", required_tools=", ".join(required_tools))
        if required_tools
        else ""
    )
    return render_prompt(
        "coding.tdd.incomplete_reminder",
        step_name=str(step.get("name") or "").strip() or "current step",
        phase_title=phase["title"],
        phase_number=int(state.get("phase_index") or 0) + 1,
        phase_total=_phase_total(state),
        phase_instructions=phase["instructions"],
        tools_suffix=tools_suffix,
    )


def build_tdd_cycle_progress_message(state: dict[str, Any]) -> str:
    if is_tdd_cycle_complete(state):
        return render_prompt("coding.tdd.complete")
    phase = current_tdd_cycle_phase(state)
    return render_prompt(
        "coding.tdd.advanced",
        phase_number=int(state.get("phase_index") or 0) + 1,
        phase_total=_phase_total(state),
        phase_title=phase["title"],
        phase_instructions=phase["instructions"],
    )
