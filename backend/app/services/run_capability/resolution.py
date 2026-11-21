"""Resolve the capability class a run executes under.

Precedence, first match wins, every step explicit and recorded as ``source``:

1. A matched workflow (the current phase of the session's workflow run): the class the
   phase declares. The request's ``agent_type`` is ignored and, when it differs
   from the run's mode, recorded as ``agent_type_ignored``.
2. A sub-agent run: the enforced class of its parent run, never more.
3. A programmatic caller's declaration (``declared_run_capability`` session metadata,
   :mod:`.declared`): the class a schedule or flow declares, a worker's profile, or the
   spawning turn's class for a sub-agent. An unsupported declared value is
   ``needs_configuration``.
4. An explicit agent definition: the capability of the definition's own mode
   (``change`` or read-only); other modes have no opinion here.
5. A chat turn without a workflow (the chat entry points always record a routing
   resolution): ``read_only``.
6. A caller whose declaration record says it declares no class (a schedule or flow
   definition without ``capability_class``): ``read_only``, recorded as
   ``undeclared_read_only``.
7. Anything else (a caller that records no declaration at all): ``needs_configuration``,
   recorded as ``missing_declaration``. There is no silent default: every run has an
   explicit profile origin, and every class is enforced.

Chat is strictly read-only. A turn outside a workflow run's phase whose class
came from a chat-side source (a routing workflow selected in chat, an agent definition's mode,
the chat default) is capped to ``read_only`` (``capped_outside_run``); a recorded
``capability_escalation=allow_changes`` raises nothing. Declared programmatic origins
(a run's platform actions, workers, schedules, flows, a parent run) keep their class.

Exception (work must be startable from the chat, ``chat_writes.py``): such a chat turn records
``chat_connector_writes``; it stays ``read_only`` for everything else but may write through its connections, each
call confirmed by the person (``tool_approval_gate``). A workflow run's phase, a sub-agent and a declared
programmatic origin never get it.

Tightening only: a run started by a parent run (``parent_session_id``) never exceeds the
parent's enforced class, whatever steps 1-6 and the escalation decided; the cap is
recorded as ``capped_by_parent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_READ_ONLY

from ...agent.runtime_defaults import get_system_agent_mode_definition
from ..workflow_contracts.decisions import (
    CAPABILITY_ESCALATION_DECISION,
    recorded_workflow_decisions,
)
from .chat_writes import CHAT_CONNECTOR_WRITES_KEY
from .classes import RUN_CAPABILITY_CLASS_KEY, capability_covers, normalize_capability_class, run_agent_mode
from .declared import (
    DECLARATION_SOURCES,
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_MISSING_DECLARATION,
    SOURCE_SUB_AGENT_PARENT,
    SOURCE_UNDECLARED_READ_ONLY,
    DeclaredRunCapability,
    declared_from_metadata,
)
from .definition_contract import declared_workflow_capability

RUN_CAPABILITY_STATUS_ALLOWED = "allowed"
RUN_CAPABILITY_STATUS_NEEDS_CONFIGURATION = "needs_configuration"

SOURCE_AGENT_DEFINITION = "agent_definition"
# ``workflow_runs.states.RUN_SELECTION_SOURCE``: the resolution of a workflow run's phase (not imported: no cycle).
RUN_PHASE_SELECTION = "workflow_run"
SOURCE_CHAT_DEFAULT = "chat_default"
# A caller that is not a chat although it declares no class: it never writes through connectors from "chat".
_PROGRAMMATIC_SOURCES = frozenset({SOURCE_UNDECLARED_READ_ONLY, SOURCE_MISSING_DECLARATION})

_READ_ONLY_MODE_CAPABILITIES = frozenset({"diagnosis", "plan"})
_MISSING_DECLARATION_REASON = (
    "The run has no profile origin: no workflow, parent run, declared capability, agent definition "
    "or chat routing resolution was recorded. The caller must declare its origin."
)


@dataclass(frozen=True, slots=True)
class RunCapabilityResolution:
    capability_class: str
    source: str
    enforced: bool
    status: str
    reason: str
    requested_agent_type: str
    effective_agent_type: str
    escalation_decision: str = ""
    escalated: bool = False
    workflow_run: bool = False
    parent_capability_class: str | None = None
    capped_by_parent: bool = False
    # The selected agent's ceiling; it only ever lowers the class.
    agent_capability_ceiling: str | None = None
    capped_by_agent: bool = False
    # A chat-side class outside a workflow run's phase is capped to read_only.
    capped_outside_run: bool = False
    # a chat turn writes through its connections, one confirmation per call (``chat_writes.py``).
    chat_connector_writes: bool = False

    @property
    def agent_type_ignored(self) -> bool:
        return bool(self.requested_agent_type) and self.requested_agent_type != self.effective_agent_type

    @property
    def declared_origin(self) -> str | None:
        """The governed non-chat origin (schedule, flow, worker, parent run) that decided the class."""
        return self.source if self.source in DECLARATION_SOURCES else None

    def to_metadata(self) -> dict[str, Any]:
        """The ``execution_profile.capability`` section."""
        return {
            RUN_CAPABILITY_CLASS_KEY: self.capability_class,
            "source": self.source,
            "enforced": self.enforced,
            "status": self.status,
            "reason": self.reason,
            "requested_agent_type": self.requested_agent_type or None,
            "effective_agent_type": self.effective_agent_type,
            "agent_type_ignored": self.agent_type_ignored,
            "escalation_decision": self.escalation_decision or None,
            "escalated": self.escalated,
            "parent_class": self.parent_capability_class,
            "capped_by_parent": self.capped_by_parent,
            "agent_ceiling": self.agent_capability_ceiling,
            "capped_by_agent": self.capped_by_agent,
            "capped_outside_run": self.capped_outside_run,
            CHAT_CONNECTOR_WRITES_KEY: self.chat_connector_writes,
        }

    def tool_context_state(self) -> dict[str, Any]:
        """The frozen state the tool dispatch gate and the security analyzer read."""
        return {
            RUN_CAPABILITY_CLASS_KEY: self.capability_class,
            "enforced": self.enforced,
            "source": self.source,
            "escalation_decision": self.escalation_decision or None,
            CHAT_CONNECTOR_WRITES_KEY: self.chat_connector_writes,
        }


def _mode_capability_class(mode_capability: str) -> str | None:
    if mode_capability == "change":
        return CAPABILITY_CHANGE
    if mode_capability in _READ_ONLY_MODE_CAPABILITIES:
        return CAPABILITY_READ_ONLY
    return None


def decide_run_capability(
    *,
    routing_resolution: Any,
    requested_agent_type: str,
    requested_mode_capability: str,
    agent_definition_mode_capability: str = "",
    parent_capability_class: str | None = None,
    recorded_decisions: dict[str, str] | None = None,
    declared_capability: DeclaredRunCapability | None = None,
    agent_capability_ceiling: str | None = None,
) -> RunCapabilityResolution:
    """Pure decision over already-loaded inputs (see the module docstring)."""
    requested = str(requested_agent_type or "").strip().lower()
    resolution = routing_resolution if isinstance(routing_resolution, dict) else None
    escalation_decision = (recorded_decisions or {}).get(CAPABILITY_ESCALATION_DECISION, "")
    workflow_run = bool(resolution and resolution.get("source") == "db" and resolution.get("status") == "matched")
    parent_class = normalize_capability_class(parent_capability_class)
    status, reason = RUN_CAPABILITY_STATUS_ALLOWED, ""
    if workflow_run:
        declared = declared_workflow_capability(resolution)
        base_class = declared.capability_class or CAPABILITY_READ_ONLY
        source = declared.source
        if declared.capability_class is None:
            status, reason = RUN_CAPABILITY_STATUS_NEEDS_CONFIGURATION, declared.error
    elif parent_class is not None:
        base_class, source = parent_class, SOURCE_SUB_AGENT_PARENT
    elif declared_capability is not None and declared_capability.source != SOURCE_UNDECLARED_READ_ONLY:
        base_class = declared_capability.capability_class or CAPABILITY_READ_ONLY
        source = declared_capability.source
        if declared_capability.capability_class is None:
            status, reason = RUN_CAPABILITY_STATUS_NEEDS_CONFIGURATION, declared_capability.error
    elif _mode_capability_class(agent_definition_mode_capability) is not None:
        base_class = str(_mode_capability_class(agent_definition_mode_capability))
        source = SOURCE_AGENT_DEFINITION
    elif resolution is not None:
        base_class, source = CAPABILITY_READ_ONLY, SOURCE_CHAT_DEFAULT
    elif declared_capability is not None:
        base_class, source = CAPABILITY_READ_ONLY, SOURCE_UNDECLARED_READ_ONLY
    else:
        base_class, source = CAPABILITY_READ_ONLY, SOURCE_MISSING_DECLARATION
        status, reason = RUN_CAPABILITY_STATUS_NEEDS_CONFIGURATION, _MISSING_DECLARATION_REASON
    escalated = False  # no escalation in chat
    capability_class = base_class
    in_run_phase = workflow_run and str((resolution or {}).get("selection_source") or "") == RUN_PHASE_SELECTION
    capped_outside_run = (
        not in_run_phase and parent_class is None and source not in DECLARATION_SOURCES
        and capability_class != CAPABILITY_READ_ONLY
    )
    if capped_outside_run:
        capability_class = CAPABILITY_READ_ONLY
    chat_connector_writes = (
        status == RUN_CAPABILITY_STATUS_ALLOWED and not in_run_phase and parent_class is None
        and source not in DECLARATION_SOURCES and source not in _PROGRAMMATIC_SOURCES
    )
    # Tightening only: a child run never exceeds the run that started it.
    capped = parent_class is not None and not capability_covers(parent_class, capability_class)
    if capped:
        capability_class = str(parent_class)
    # The selected agent's ceiling caps every source alike: workflow, declaration, escalation.
    ceiling = normalize_capability_class(agent_capability_ceiling)
    capped_by_agent = ceiling is not None and not capability_covers(ceiling, capability_class)
    if capped_by_agent:
        capability_class = str(ceiling)
    effective_mode = run_agent_mode(
        capability_class,
        workflow_run=workflow_run,
        requested_mode_key=requested,
        requested_mode_capability=requested_mode_capability,
    )
    return RunCapabilityResolution(
        capability_class=capability_class,
        source=source,
        enforced=True,
        status=status,
        reason=reason,
        requested_agent_type=requested,
        effective_agent_type=effective_mode,
        escalation_decision=escalation_decision,
        escalated=escalated and not capped and not capped_by_agent,
        workflow_run=workflow_run,
        parent_capability_class=parent_class,
        capped_by_parent=capped,
        agent_capability_ceiling=ceiling,
        capped_by_agent=capped_by_agent,
        capped_outside_run=capped_outside_run,
        chat_connector_writes=chat_connector_writes,
    )


async def _mode_capability(db: Any, mode_key: str) -> str:
    key = str(mode_key or "").strip().lower()
    if not key:
        return ""
    system_mode = get_system_agent_mode_definition(key)
    if system_mode is not None:
        return system_mode.capability_type
    from ..agent_mode import resolve_agent_mode

    return (await resolve_agent_mode(db, key)).capability_type


async def _parent_capability_class(db: Any, parent_session_id: str | None) -> str | None:
    if not parent_session_id or db is None:
        return None
    from ...models import Session

    parent = await db.get(Session, parent_session_id)
    profile = (parent.metadata_ or {}).get("execution_profile") if parent is not None else None
    capability = profile.get("capability") if isinstance(profile, dict) else None
    if not isinstance(capability, dict) or capability.get("enforced") is not True:
        return None
    return normalize_capability_class(capability.get(RUN_CAPABILITY_CLASS_KEY))


async def resolve_run_capability(
    db: Any,
    *,
    session_metadata: dict[str, Any],
    routing_resolution: Any,
    requested_agent_type: str,
    agent_definition: dict[str, Any] | None,
    parent_session_id: str | None,
) -> RunCapabilityResolution:
    """Load the inputs of :func:`decide_run_capability` and decide."""
    definition = agent_definition if isinstance(agent_definition, dict) else {}
    from ..platform_agents.catalog import is_platform_agent_key

    # A platform agent has no mode of its own: it never decides the class.
    mode_key = "" if is_platform_agent_key(definition.get("builtinKey")) else str(definition.get("agent_type") or "")
    definition_mode_capability = str(definition.get("capability_type") or "").strip().lower() or (
        await _mode_capability(db, mode_key)
    )
    return decide_run_capability(
        routing_resolution=routing_resolution,
        requested_agent_type=requested_agent_type,
        requested_mode_capability=await _mode_capability(db, requested_agent_type),
        agent_definition_mode_capability=definition_mode_capability,
        parent_capability_class=await _parent_capability_class(db, parent_session_id),
        recorded_decisions=recorded_workflow_decisions(session_metadata),
        declared_capability=declared_from_metadata(session_metadata.get(DECLARED_RUN_CAPABILITY_METADATA_KEY)),
        agent_capability_ceiling=(str(definition.get("capabilityCeiling") or "") or None) if definition else None,
    )


__all__ = [
    "RUN_CAPABILITY_STATUS_ALLOWED",
    "RUN_CAPABILITY_STATUS_NEEDS_CONFIGURATION",
    "SOURCE_AGENT_DEFINITION",
    "SOURCE_CHAT_DEFAULT",
    "RunCapabilityResolution",
    "decide_run_capability",
    "resolve_run_capability",
]
