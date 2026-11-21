"""Per-iteration tool surface of a standard loop request: step, final answer and offer limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services.agent_tool_surface_contract import denies_tools

from ....services.chat_deferred_tools import sent_chat_tool_definitions
from ....services.tool_surface_budget_policy import budget_tool_definitions_for_runtime
from ....tools.definitions import get_all_definitions, is_tool_definition_available_for_agent_type
from ...core.context._context_discovery_surface import discovery_tool_surface, is_discovery_mode
from ...core.guards.response_guards import get_step_allowed_tools
from ...core.guards.step_progress import detect_step_tool_stagnation
from ..response._loop_message_dedupe import dedupe_runtime_control_messages

if TYPE_CHECKING:
    from ._loop_request_messages import RuntimeMessagesInputs



def tool_names_of(tool_definitions: list[dict[str, Any]]) -> set[Any]:
    return {
        definition.get("function", {}).get("name")
        for definition in tool_definitions
        if definition.get("function", {}).get("name")
    }


@dataclass
class RequestSurface:
    """What the request offers and sends so far; the phases below rebind its fields in loop order."""

    tool_definitions: list[dict[str, Any]]
    allowed_tool_names: set[Any]
    request_messages: list[dict[str, Any]]

    def refresh_allowed(self) -> None:
        self.allowed_tool_names = tool_names_of(self.tool_definitions)


def _ensure_named_tool_definitions(
    tool_definitions: list[dict[str, Any]], required_tool_names: set[str], *, agent_type: str
) -> list[dict[str, Any]]:
    existing_names = {
        str(definition.get("function", {}).get("name") or "").strip()
        for definition in tool_definitions
        if isinstance(definition, dict)
    }
    missing_names = {tool_name for tool_name in required_tool_names if tool_name and tool_name not in existing_names}
    if not missing_names:
        return tool_definitions

    all_definitions = get_all_definitions()
    additions = [
        definition
        for tool_name in sorted(missing_names)
        if (definition := all_definitions.get(tool_name))
        and isinstance(definition, dict)
        and is_tool_definition_available_for_agent_type(tool_name, agent_type)
    ]
    if not additions:
        return tool_definitions
    return [*tool_definitions, *additions]


def apply_step_tool_surface(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    *,
    planning_tool_history: list[dict[str, Any]],
) -> None:
    current_step = inputs.current_step
    step_allowed_tools = {
        str(tool_name).strip() for tool_name in get_step_allowed_tools(current_step) if str(tool_name).strip()
    }
    step_allowed_tools = inputs._augment_step_allowed_tools_for_request_analysis(
        step_allowed_tools, inputs.request_analysis
    )
    surface.tool_definitions = inputs.filter_tool_definitions(
        surface.tool_definitions,
        step_allowed_tools or get_step_allowed_tools(current_step),
    )
    surface.refresh_allowed()
    surface.request_messages = dedupe_runtime_control_messages(inputs.messages) + [
        {
            "role": "system",
            "content": inputs.build_current_step_prompt(
                inputs.current_step_for_runtime or current_step,
                inputs.current_step_index + 1,
                len(inputs.active_steps),
                (inputs.agent_definition or {}).get("branchPrefix"),
            ),
        }
    ]
    stagnation_message = detect_step_tool_stagnation(current_step, planning_tool_history)
    if stagnation_message:
        surface.request_messages = surface.request_messages + [{"role": "system", "content": stagnation_message}]


def apply_artifact_ready_surface(
    inputs: RuntimeMessagesInputs,
    surface: RequestSurface,
    *,
    effective_workflow_contract: dict[str, Any] | None,
    workflow_final_answer_prompted: bool,
) -> bool:
    """A finished workflow artifact leaves no tools; returns the updated final-answer-prompted flag."""
    surface.tool_definitions = []
    surface.allowed_tool_names = set()
    if not workflow_final_answer_prompted:
        workflow_msg = {
            "role": "system",
            "content": inputs._build_workflow_artifact_ready_message(effective_workflow_contract),
        }
        workflow_final_answer_prompted = True
    else:
        workflow_msg = None
    # Never mutate the caller's messages list
    surface.request_messages = dedupe_runtime_control_messages(inputs.messages)
    if workflow_msg:
        surface.request_messages = [*surface.request_messages, workflow_msg]
    return workflow_final_answer_prompted


def apply_offer_limits(
    inputs: RuntimeMessagesInputs, surface: RequestSurface, context_snapshot: dict[str, Any]
) -> tuple[Any, bool]:
    """Deferred catalog, provider budget, discovery mode and text-only agents; returns (deferred_catalog, text_only)."""
    tool_context = inputs.tool_context
    context_plan = inputs.context_plan
    # A chat turn sends its core tools and the loaded ones in full, the rest by name (``chat_deferred_tools``); a tool
    # loaded with ``tool_search`` is sent from the next model call on.
    offered_tool_names = {name for definition in surface.tool_definitions
                          if (name := definition.get("function", {}).get("name"))}
    deferred_catalog = getattr(tool_context, "deferred_tool_catalog", None)
    if deferred_catalog:
        surface.tool_definitions = sent_chat_tool_definitions(
            surface.tool_definitions, deferred_catalog, getattr(tool_context, "discovered_tool_names", None))
        context_snapshot["deferred_tool_count"] = len(offered_tool_names) - len(surface.tool_definitions)
    offered_before_budget = [definition.get("function", {}).get("name") for definition in surface.tool_definitions]
    surface.tool_definitions = budget_tool_definitions_for_runtime(
        surface.tool_definitions,
        runtimes=inputs.current_runtimes,
        capability_type=inputs.capability_type,
        coding_discipline=inputs.current_coding_discipline,
        priority_tool_names=context_plan.tool_allowlist if getattr(context_plan, "tool_surface_set", "") else None,
    )
    surface.refresh_allowed()
    cut_by_budget = [name for name in offered_before_budget if name and name not in surface.allowed_tool_names]
    if cut_by_budget:
        # Never silent: the turn records which tools the provider cap removed.
        context_snapshot["tool_budget_cut"] = cut_by_budget
    if deferred_catalog:
        # A deferred tool stays callable by the name the catalog shows (a weak model may call it directly).
        surface.allowed_tool_names |= offered_tool_names
    # Opt-in discovery mode: replace the keyword-routed allowlist with a small
    # always-on core surface + tool_search/tool_schema_get; long-tail tools are
    # reached on demand. Runs per iteration, so tools the model activated via
    # tool_schema_get this turn appear on the next step.
    if is_discovery_mode(getattr(tool_context, "project_config", None), inputs.runtime_settings):
        surface.tool_definitions, surface.allowed_tool_names = discovery_tool_surface(
            capability_type=inputs.capability_type,
            discovered_tool_names=getattr(tool_context, "discovered_tool_names", None),
            project_config=getattr(tool_context, "project_config", None),
        )
        context_snapshot["tool_surface_mode"] = "discovery"
    text_only_agent = denies_tools(getattr(tool_context, "agent_definition", None))
    if text_only_agent:
        # No tools (text only) outranks every per-iteration addition, discovery included.
        surface.tool_definitions, surface.allowed_tool_names = [], set()
    context_snapshot["tool_definition_count"] = len(surface.tool_definitions)
    context_snapshot["tool_names"] = sorted(surface.allowed_tool_names)
    return deferred_catalog, text_only_agent
