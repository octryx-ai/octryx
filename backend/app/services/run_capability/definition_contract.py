"""The capability class a workflow definition declares, and its validation.

The class lives on the workflow contract (``workflow_contract.capability_class``): the
contract is the one thing a selected workflow hands to the run, so the run reads its
capability from the same governed, versioned, published payload as its tool policy.

The validator refuses a definition whose tools exceed its class (for example a write
tool in a ``read_only`` definition) and one whose declared safety constraints contradict
it, and refuses a definition without a class. A workflow resolution that declares no
class (or an unsupported one) is the explicit state ``needs_configuration`` at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...tools.capability_requirements import CAPABILITY_READ_ONLY, is_known_tool, tool_required_capability
from ...tools.definitions import get_all_definitions
from ..workflow_routing.tool_policy import normalized_tool_policy, string_list, tool_name_matches_any_pattern
from .classes import CAPABILITY_CLASSES, capability_covers, normalize_capability_class

CAPABILITY_CLASS_CONTRACT_KEY = "capability_class"
SOURCE_WORKFLOW_DEFINITION = "workflow_definition"


@dataclass(frozen=True, slots=True)
class DeclaredCapability:
    """The class a matched workflow declares; ``capability_class`` is None when invalid."""

    capability_class: str | None
    source: str
    error: str = ""


def _definition_tool_names(workflow_contract: dict[str, Any], tool_policy: dict[str, Any]) -> list[str]:
    policy = normalized_tool_policy(tool_policy)
    names = [*policy["allowlist"], *policy["high_risk_grants"]]
    if policy["allow_patterns"]:
        denied = set(policy["denylist"])
        names.extend(
            name
            for name in get_all_definitions()
            if tool_name_matches_any_pattern(name, policy["allow_patterns"])
            and name not in denied
            and not tool_name_matches_any_pattern(name, policy["deny_patterns"])
        )
    names.extend(list(dict.fromkeys(string_list(workflow_contract.get("allowed_tools")))))
    steps = workflow_contract.get("source_steps")
    if isinstance(steps, list):
        names.extend(
            list(dict.fromkeys(
                [str(step.get("tool") or "").strip() for step in steps if isinstance(step, dict) and step.get("tool")]
            ))
        )
    return sorted(set(names))


def validate_definition_capability_class(
    *,
    is_definition: bool,
    workflow_contract: Any,
    tool_policy: Any,
    safety_constraints: Any,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return ``(errors, warnings)`` for the declared capability class of a policy version."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    raw_class = contract.get(CAPABILITY_CLASS_CONTRACT_KEY)
    options = ", ".join(CAPABILITY_CLASSES)
    if raw_class is None or raw_class == "":
        issue = {
            "code": "missing_capability_class",
            "message": f"workflow_contract.capability_class is required; one of: {options}.",
        }
        return ([issue], []) if is_definition else ([], [issue])
    capability_class = normalize_capability_class(raw_class)
    if capability_class is None:
        return [
            {
                "code": "unsupported_capability_class",
                "message": f"workflow_contract.capability_class must be one of: {options}.",
            }
        ], []
    errors: list[dict[str, str]] = []
    exceeding: dict[str, list[str]] = {}
    for name in _definition_tool_names(contract, tool_policy if isinstance(tool_policy, dict) else {}):
        if not is_known_tool(name):
            errors.append({"code": "unknown_tool", "message": f"unknown tool: {name}."})
            continue
        required = tool_required_capability(name)
        if not capability_covers(capability_class, required):
            exceeding.setdefault(required, []).append(name)
    for required, names in sorted(exceeding.items()):
        errors.append(
            {
                "code": "capability_class_exceeded",
                "message": (
                    f"A '{capability_class}' workflow cannot allow tools that need '{required}': "
                    f"{', '.join(names)}."
                ),
            }
        )
    safety = safety_constraints if isinstance(safety_constraints, dict) else {}
    if capability_class == CAPABILITY_READ_ONLY and bool(safety.get("allow_mutating_tools")):
        errors.append(
            {
                "code": "capability_class_safety_conflict",
                "message": "A 'read_only' workflow cannot set safety_constraints.allow_mutating_tools.",
            }
        )
    if capability_class != CAPABILITY_READ_ONLY and bool(safety.get("diagnosis_mode")):
        errors.append(
            {
                "code": "capability_class_safety_conflict",
                "message": f"A '{capability_class}' workflow cannot set safety_constraints.diagnosis_mode.",
            }
        )
    return errors, []


def declared_workflow_capability(resolution: dict[str, Any]) -> DeclaredCapability:
    """The class a matched routing resolution declares (see the module docstring)."""
    contract = resolution.get("workflow_contract") if isinstance(resolution.get("workflow_contract"), dict) else {}
    raw_class = contract.get(CAPABILITY_CLASS_CONTRACT_KEY)
    capability_class = normalize_capability_class(raw_class) if raw_class not in (None, "") else None
    if capability_class is None:
        problem = "an unsupported" if raw_class not in (None, "") else "no"
        return DeclaredCapability(
            capability_class=None,
            source=SOURCE_WORKFLOW_DEFINITION,
            error=(
                f"The selected workflow declares {problem} capability_class; "
                f"an admin must set one of: {', '.join(CAPABILITY_CLASSES)}."
            ),
        )
    return DeclaredCapability(capability_class=capability_class, source=SOURCE_WORKFLOW_DEFINITION)


__all__ = [
    "CAPABILITY_CLASS_CONTRACT_KEY",
    "SOURCE_WORKFLOW_DEFINITION",
    "DeclaredCapability",
    "declared_workflow_capability",
    "validate_definition_capability_class",
]
