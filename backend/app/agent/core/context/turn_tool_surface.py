"""The tool surface of a turn, from explicit sources only.

The context planner sizes tier and context; it never decides whether a turn has tools. This
module sets ``include_tools``, ``tool_allowlist`` and ``tool_surface_source`` on the planned
turn from a closed precedence of explicit sources.

0. ``agent_no_tools``: an agent that does not declare ``governed`` (``toolSurface: none``)
   gets no tools at all. This is a deny boundary that outranks every source below. A selected
   workflow does not widen it: the execution gate stops such a turn as ``needs_configuration``
   (``services/agent_tool_surface.py``).
0b. ``phase_without_tool_policy``: a phase turn of a workflow run whose phase declares no
   ``tool_policy`` allow rules gets no tools (fail closed). A phase's surface is its own policy;
   the family surface of the ``workflow_id`` it reuses never stands in for it.

Otherwise the first source that declares a surface wins:

1. ``selected_definition``: the selected workflow definition's ``tool_policy`` allow rules
   (``source="db"``, ``status="matched"``: explicit ``workflow_key`` or DB policy), together
   with the contract's ``allowed_tools``. A pattern-only policy still turns tools on; the
   tool-definition build expands the patterns, and the run-context routing tool policy bounds
   the offered set to the definition's rules.
2. ``selected_workflow``: the strategy's selected workflow without definition allow rules; its
   contract ``allowed_tools``, else the family surface of its ``workflow_id``.
3. ``agent_definition``: the agent blueprint's tools, when every enabled step declares its
   ``allowedTools``. A step without a declared list works on the full surface, so such a
   blueprint does not bound the turn.
4. ``workspace_policy``: the Workspace tool policy declares allow rules; the capability's
   catalog filtered by that policy is the surface.
5. ``governed_default``: the closed, versioned default tool set of the turn's capability class
   (``services/governed_default_tool_sets``); the plan records the set's key
   (``tool_surface_set``, e.g. ``diagnosis.v1``) and keeps the set's declared priority order.
   A chat turn (``run_capability/chat_writes.py``) additionally gets the connector
   write tools after the set's core families; connector visibility keeps only those its connections allow
   (agent tools level ``write``), and the person confirms each call before it runs. The model sees a chat
   turn's core tools in full and the rest by name (``services/chat_deferred_tools``).

Every level offers tools. The capability catalog, connector visibility and the Workspace
policy's deny and read-only rules filter every level afterwards
(``run_context_tooling.build_run_context_tool_definitions``), and the loop trims by provider
limits deterministically. A turn therefore offers zero tools only when these explicit filters
leave nothing; the context snapshot records the source and the offered tool names.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.services.agent_tool_surface_contract import denies_tools

from ....services.governed_default_tool_sets import default_tool_set_key_for_class, governed_default_tool_set
from ....services.run_capability.chat_write_plan import PROPOSE_WRITE_PLAN
from ....services.run_capability.chat_writes import chat_connector_write_tool_names
from ....services.session.turn_tool_surface_record import (
    TOOL_SURFACE_AGENT_DEFINITION,
    TOOL_SURFACE_AGENT_NO_TOOLS,
    TOOL_SURFACE_GOVERNED_DEFAULT,
    TOOL_SURFACE_PHASE_WITHOUT_POLICY,
    TOOL_SURFACE_SELECTED_DEFINITION,
    TOOL_SURFACE_SELECTED_WORKFLOW,
    TOOL_SURFACE_WORKSPACE_POLICY,
    record_tool_surface_metadata,
)
from ....services.tool_access_policy_config import project_tool_policy_has_allow_rules
from ....services.workflow_routing.tool_policy import normalized_tool_policy, tool_policy_has_allow_rules
from ....services.workflow_runs.phase_marker import is_run_phase_contract
from ..guards.response_guards import get_step_allowed_tools
from .context_planner import ContextPlan, context_plan_log_fields
from .tool_families import (
    COMMON_READ_ONLY_TOOLS,
    GOVERNED_KNOWLEDGE_TOOLS,
    KNOWLEDGE_FORBIDDEN_TOOLS,
)

logger = logging.getLogger(__name__)

# Explicit workflow_id -> the tool family that selected workflow needs when its contract does
# not enumerate its tools. Governed evidence only (the Knowledge ledger).
_WORKFLOW_TOOL_SURFACE: dict[str, list[str]] = {
    "knowledge_request": GOVERNED_KNOWLEDGE_TOOLS,
}


def selected_definition_tool_allowlist(routing_resolution: dict[str, Any] | None) -> list[str] | None:
    """The allowlist of the turn's selected definition, or ``None`` when it declares no allow rules.

    Only a matched definition (``source="db"``, ``status="matched"``: the current phase of the session's
    workflow run) counts. A pattern-only policy returns an empty list: the turn still
    needs tools, and the tool-definition build expands the patterns against the registry.
    """
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    if resolution.get("source") != "db" or resolution.get("status") != "matched":
        return None
    policy = normalized_tool_policy(resolution.get("tool_policy"))
    if not tool_policy_has_allow_rules(policy):
        return None
    return list(policy["allowlist"])


def resolve_workflow_tool_surface(
    *,
    workflow_id: str | None,
    workflow_contract: dict[str, Any] | None,
    definition_allowlist: list[str] | None = None,
) -> list[str] | None:
    """The allowlist a selected workflow requires, or ``None`` when no workflow declares one.

    Priority: the selected definition's ``tool_policy`` allowlist together with the contract's
    own ``allowed_tools``; then the contract's ``allowed_tools`` (managed profiles); then the
    family surface of the explicit ``workflow_id``.
    """
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    explicit = list(dict.fromkeys(
        str(tool).strip() for tool in (contract.get("allowed_tools") or []) if str(tool).strip()
    ))
    if definition_allowlist is not None:
        # The selected definition governs its surface; the run-context tool policy then bounds
        # the offered set to exactly this allowlist (plus the contract's tools).
        return list(dict.fromkeys([*explicit, *definition_allowlist, *COMMON_READ_ONLY_TOOLS]))
    if explicit:
        # A managed profile enumerated its own tools; honour them verbatim.
        return list(dict.fromkeys([*explicit, *COMMON_READ_ONLY_TOOLS]))
    base = _WORKFLOW_TOOL_SURFACE.get(str(workflow_id or "").strip())
    if not base:
        return None
    forbidden = set(KNOWLEDGE_FORBIDDEN_TOOLS)
    return [tool for tool in dict.fromkeys([*base, *COMMON_READ_ONLY_TOOLS]) if tool not in forbidden]


def agent_definition_tool_allowlist(agent_definition: dict[str, Any] | None) -> list[str] | None:
    """The blueprint's tools when every enabled step declares them, else ``None``."""
    steps = (agent_definition or {}).get("steps") or []
    enabled_steps = [
        step for step in steps if isinstance(step, dict) and (step.get("isEnabled") or step.get("is_enabled"))
    ]
    if not enabled_steps:
        return None
    step_tools = [get_step_allowed_tools(step) for step in enabled_steps]
    if not all(step_tools):
        return None
    return list(dict.fromkeys([*(tool for tools in step_tools for tool in tools), *COMMON_READ_ONLY_TOOLS]))


def workflow_declares_tool_surface(
    *, workflow_id: str | None, workflow_contract: dict[str, Any] | None, routing_resolution: dict[str, Any] | None
) -> bool:
    """True when the turn's selected definition or selected workflow declares a tool surface."""
    return (
        resolve_workflow_tool_surface(
            workflow_id=workflow_id,
            workflow_contract=workflow_contract,
            definition_allowlist=selected_definition_tool_allowlist(routing_resolution),
        )
        is not None
    )


# The families a provider cap must cut last: up to here the governed set is what every chat needs; the connector
# writes the person asks for come right after, before the MCP bridge, the shell and delegation.
_CHAT_WRITES_AFTER_FAMILY = "connector_read"


def _chat_surface(default_set: Any) -> list[str]:
    """A chat turn's surface: the governed set with the connector writes seated after its core families.

    a "write" Jira connection, yet the chat had no create_jira_ticket (chat_writes.py). Under a
    provider cap (copilot: 96) the declared order decides the cut (``tool_surface_budget_policy``); appended after the
    whole set, the writes the person explicitly asks for were the first to go."""
    families = list(default_set.families)
    split = next((index + 1 for index, family in enumerate(families) if family.name == _CHAT_WRITES_AFTER_FAMILY),
                 len(families))
    core = [tool for family in families[:split] for tool in family.tools]
    rest = [tool for family in families[split:] for tool in family.tools]
    # The chat's writes run under one plan the person confirms once (``chat_write_plan``).
    return list(dict.fromkeys([*core, PROPOSE_WRITE_PLAN, *chat_connector_write_tool_names(), *rest]))


def resolve_turn_tool_surface(
    plan: ContextPlan,
    *,
    capability_type: str,
    workflow_id: str | None,
    workflow_contract: dict[str, Any] | None,
    routing_resolution: dict[str, Any] | None,
    agent_definition: dict[str, Any] | None,
    project_config: dict[str, Any] | None,
    capability_class: str | None = None,
    chat_connector_writes: bool = False,
) -> ContextPlan:
    """Set the turn's tool surface from the first explicit source that declares one."""
    if denies_tools(agent_definition):
        return replace(plan, include_tools=False, tool_allowlist=[], tool_surface_source=TOOL_SURFACE_AGENT_NO_TOOLS)
    definition_allowlist = selected_definition_tool_allowlist(routing_resolution)
    phase_turn = is_run_phase_contract(workflow_contract) or is_run_phase_contract(
        (routing_resolution or {}).get("workflow_contract") if isinstance(routing_resolution, dict) else None)
    if phase_turn and definition_allowlist is None:
        return replace(plan, include_tools=False, tool_allowlist=[],
                       tool_surface_source=TOOL_SURFACE_PHASE_WITHOUT_POLICY)
    workflow_surface = resolve_workflow_tool_surface(
        workflow_id=workflow_id,
        workflow_contract=workflow_contract,
        definition_allowlist=definition_allowlist,
    )
    if workflow_surface is not None:
        source = (
            TOOL_SURFACE_SELECTED_DEFINITION if definition_allowlist is not None else TOOL_SURFACE_SELECTED_WORKFLOW
        )
        return replace(plan, include_tools=True, tool_allowlist=sorted(set(workflow_surface)), tool_surface_source=source)
    agent_tools = agent_definition_tool_allowlist(agent_definition)
    if agent_tools is not None:
        return replace(
            plan,
            include_tools=True,
            tool_allowlist=sorted(set(agent_tools)),
            tool_surface_source=TOOL_SURFACE_AGENT_DEFINITION,
        )
    if project_tool_policy_has_allow_rules(project_config):
        return replace(plan, include_tools=True, tool_allowlist=None, tool_surface_source=TOOL_SURFACE_WORKSPACE_POLICY)
    # The governed default follows the run's capability class; the mode is only a fallback label.
    default_set = governed_default_tool_set(default_tool_set_key_for_class(capability_class) or capability_type)
    # Declared order, not sorted: it is the set's priority under a provider cap.
    tools = list(default_set.tools)
    if chat_connector_writes:
        tools = _chat_surface(default_set)
    return replace(
        plan,
        include_tools=True,
        tool_allowlist=tools,
        tool_surface_source=TOOL_SURFACE_GOVERNED_DEFAULT,
        tool_surface_set=default_set.key,
    )


def plan_and_record_turn_tool_surface(
    plan: ContextPlan,
    *,
    session_id: str,
    session_metadata: dict[str, Any],
    current_session: Any,
    capability_type: str,
    strategy_decision: Any,
    routing_resolution: dict[str, Any] | None,
    agent_definition: dict[str, Any] | None,
    project_config: dict[str, Any] | None,
    capability_class: str | None = None,
    chat_connector_writes: bool = False,
) -> ContextPlan:
    """Resolve the turn's surface and record its source and set on the session."""
    plan = resolve_turn_tool_surface(
        plan,
        capability_type=capability_type,
        workflow_id=strategy_decision.workflow_id,
        workflow_contract=strategy_decision.workflow_contract,
        routing_resolution=routing_resolution,
        agent_definition=agent_definition,
        project_config=project_config,
        capability_class=capability_class,
        chat_connector_writes=chat_connector_writes,
    )
    denied = set((agent_definition or {}).get("toolsDeny") or [])
    if denied and plan.tool_allowlist is not None:
        # An agent's optional tools_deny only narrows the surface; an agent never grants tools.
        plan = replace(plan, tool_allowlist=[tool for tool in plan.tool_allowlist if tool not in denied])
    record_tool_surface_metadata(session_metadata, source=plan.tool_surface_source, surface_set=plan.tool_surface_set)
    if current_session is not None:
        current_session.metadata_ = dict(session_metadata)
        flag_modified(current_session, "metadata_")
    logger.info("agent.prepare.context_planned", extra={"session_id": session_id, **context_plan_log_fields(plan)})
    return plan


__all__ = [
    "agent_definition_tool_allowlist",
    "plan_and_record_turn_tool_surface",
    "resolve_turn_tool_surface",
    "resolve_workflow_tool_surface",
    "selected_definition_tool_allowlist",
    "workflow_declares_tool_surface",
]
