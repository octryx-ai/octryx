"""The tool plan of a phase turn of a workflow run: the phase's own tool surface, nothing narrower.

The turn's catalog is already the phase's surface — its ``tool_policy`` allowlist, bounded by the capability class,
the phase agent's ``tools_deny`` and the Workspace / approval / MCP policies (``run_context_tooling``). The plan
selects that whole surface and declares no plan budget: the loop's iteration limit and the phase's checks bound the
turn. The execution-control contract keeps that whole surface as a hard boundary before dispatch and cache (a call
outside it is refused, an empty surface denies every call) and has no budget gate.

A phase reuses a family ``workflow_id`` for its contract message; no code-registry definition with that id
feeds this plan.
"""

from __future__ import annotations

from typing import Any

PHASE_INTENT = "workflow_phase"
PHASE_STOP_CRITERIA = ["phase_tool_policy_surface", "phase_checks_decide_completion"]
PHASE_FALLBACK_POLICY = "phase_tool_policy"
PHASE_RUNTIME_EFFECT = "phase_surface_gate_no_budget"
PHASE_EMPTY_EFFECT = "phase_surface_empty_deny_all"
PHASE_REFUSAL_CODE = "phase_tool_not_offered"


def phase_tool_plan(catalog_entries: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], int]:
    """``(selected tools, stop criteria, max tool calls)``; ``0`` calls means no plan budget."""
    selected = [
        {
            "tool": name,
            "reason": "Part of the phase's governed tool surface (phase tool policy).",
            "expected_evidence": ["phase_check_evidence", "auditable_tool_trace"],
        }
        for name in catalog_entries
    ]
    return selected, list(PHASE_STOP_CRITERIA), 0


def phase_execution_control(base: dict[str, Any], plan_contract: dict[str, Any]) -> dict[str, Any]:
    """The execution-control contract of a phase turn: the whole phase surface is the gate, there is no budget.

    The surface is taken from the plan untruncated (a phase may offer more tools than a trace shows); an empty
    surface (no policy, nothing left after the filters) denies every call — never "unlimited".
    """
    surface = list(dict.fromkeys(
        str(item.get("tool") or "").strip()
        for item in plan_contract.get("selected_tools") or []
        if isinstance(item, dict) and str(item.get("tool") or "").strip()
    ))
    enforcement = {"enabled": True, "selected_tool_gate": True, "budget_gate": False, "max_tool_calls": 0}
    if not surface:
        enforcement["deny_all_tools"] = True
    return {
        **base,
        "status": "ready" if surface else "blocked",
        "selected_tools": surface,
        "budget": {"max_tool_calls": 0, "planned_tool_count": len(surface), "remaining_after_plan": 0,
                   "budget_exceeded": False},
        "runtime_effect": PHASE_RUNTIME_EFFECT if surface else PHASE_EMPTY_EFFECT,
        "blockers": [] if surface else ["phase_tool_surface_empty"],
        "enforcement": enforcement,
    }


def phase_call_refusal(tool_name: str, contract: dict[str, Any]) -> dict[str, Any] | None:
    """Refuse a call outside the phase surface before dispatch and cache; never a budget refusal.

    No step-contract or summary-domain exception applies: an agent's steps never widen the phase.
    """
    enforcement = contract.get("enforcement") if isinstance(contract.get("enforcement"), dict) else {}
    surface = {str(item).strip() for item in contract.get("selected_tools") or [] if str(item).strip()}
    if not enforcement.get("deny_all_tools") and tool_name in surface:
        return None
    return {
        "error": (f"Tool '{tool_name}' is not part of this phase's tool surface. "
                  f"Phase tools: {', '.join(sorted(surface)) or 'none'}"),
        "code": PHASE_REFUSAL_CODE,
        "reason": "tool_not_in_phase_surface",
        "allowed_tools": sorted(surface),
        "contract_kind": contract.get("contract_kind"),
        "intent_class": contract.get("intent_class"),
    }


__all__ = [
    "PHASE_EMPTY_EFFECT",
    "PHASE_FALLBACK_POLICY",
    "PHASE_REFUSAL_CODE",
    "PHASE_INTENT",
    "PHASE_RUNTIME_EFFECT",
    "phase_call_refusal",
    "phase_execution_control",
    "phase_tool_plan",
]
