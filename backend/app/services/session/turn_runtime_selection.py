"""The runtime target a turn runs on, and the one source it came from.

Closed precedence, first match wins (``RuntimeSelectionSource``):

1. ``explicit``: the caller's runtime (unknown: ``runtime_target_invalid``; outside the
   Workspace assignment policy: ``runtime_not_allowed``);
2. ``session``: the thread's runtime, when its recorded source (``runtime_selection_source``) is an explicit
   choice or the thread's own runtime;
3. ``agent``: the selected agent definition's runtime;
4. ``workflow``: the runtime the selected workflow's ``required_model_capability``
   needs (``turn_runtime_requirement``);
5. ``workspace_default``: the Workspace composition's default runtime;
6. ``global_default``: the automatic chain (empty id), in control-plane priority order.

A ``selected_only`` Workspace with no active runtime on its list is refused
(``runtime_not_allowed``) before any source is read: the automatic chain would otherwise
answer on a runtime the Workspace does not allow.

Every source is judged by the one model resolver's gates (``services/model_selection``):
the model must be enabled in the Model catalog, allowed in the Workspace,
cleared for its data class (every driver) and, for a workflow, have the required
capability as an explicit catalog checkbox (no model-name heuristic). An implicit
runtime that fails a gate is skipped; an explicit one is refused (capability:
``runtime_requirement_unmet``, anything else: ``runtime_not_allowed`` naming the reason).
The workflow source takes the first model of the platform order that passes. No source
reads the prompt. The loop keeps the chosen chain for every iteration of the
turn; only the provider fallback's explicit, logged failover changes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ..control_plane_service import get_runtime_targets
from ..model_selection.gates import REASON_CAPABILITY, WorkspaceScope, gate, reason_text
from ..model_selection.snapshot import SelectionSnapshot, load_scope, load_snapshot
from ..runtime_options import list_chat_runtime_options
from ..workspace_composition.assignment_policy import (
    RUNTIME_NOT_ALLOWED_DETAIL,
    is_runtime_allowed,
    runtime_assignment_mode,
    selected_runtime_target_ids,
)
from ..workspace_composition.execution_view import normalize_workspace_execution_view
from .turn_preparation import resolve_initial_runtime_selection
from .turn_refusals import TurnRefusalState, TurnRefusedError
from .turn_runtime_requirement import UnsupportedModelCapabilityError, required_model_capability

RUNTIME_SELECTION_SOURCE_METADATA_KEY = "runtime_selection_source"


class RuntimeSelectionSource(StrEnum):
    EXPLICIT = "explicit"
    SESSION = "session"
    AGENT = "agent"
    WORKFLOW = "workflow"
    WORKSPACE_DEFAULT = "workspace_default"
    GLOBAL_DEFAULT = "global_default"


# A thread keeps a runtime only when a person chose it; an implicit pick is re-derived per turn.
_STICKY_SOURCES = frozenset({RuntimeSelectionSource.EXPLICIT.value, RuntimeSelectionSource.SESSION.value})


@dataclass(slots=True)
class RuntimeChoice:
    runtime_target_id: str
    runtime_label: str
    labels: dict[str, str]
    source: RuntimeSelectionSource = field(default=RuntimeSelectionSource.GLOBAL_DEFAULT)

    def choose(self, runtime_target_id: str, source: RuntimeSelectionSource) -> None:
        self.runtime_target_id = runtime_target_id
        self.runtime_label = self.labels.get(runtime_target_id, self.labels[""])
        self.source = source


def require_runtime_allowed(workspace_execution_view: dict | None, *, runtime_target_id: str) -> None:
    if not is_runtime_allowed(workspace_execution_view, runtime_target_id=runtime_target_id):
        raise TurnRefusedError(TurnRefusalState.RUNTIME_NOT_ALLOWED, RUNTIME_NOT_ALLOWED_DETAIL)


async def initial_runtime_choice(
    db: AsyncSession, *, runtime_target_id: str, runtime_target_id_explicit: bool
) -> RuntimeChoice:
    """The caller's runtime before any policy: an unknown explicit id is ``runtime_target_invalid``."""
    labels = {option["value"]: option["label"] for option in await list_chat_runtime_options(db)}
    selection = resolve_initial_runtime_selection(
        runtime_target_id=runtime_target_id,
        runtime_label_by_id=labels,
        runtime_target_id_explicit=runtime_target_id_explicit,
    )
    explicit = runtime_target_id_explicit and bool(selection.runtime_target_id)
    return RuntimeChoice(
        runtime_target_id=selection.runtime_target_id,
        runtime_label=selection.runtime_label,
        labels=labels,
        source=RuntimeSelectionSource.EXPLICIT if explicit else RuntimeSelectionSource.GLOBAL_DEFAULT,
    )


def sticky_session_runtime_target_id(session: AgentSession | None) -> str:
    """The thread's runtime when a person chose it (an implicit pick is re-derived per turn), else ``""``."""
    return _session_runtime_target_id(session)


def _session_runtime_target_id(session: AgentSession | None) -> str:
    metadata = dict(session.metadata_ or {}) if session is not None else {}
    if metadata.get(RUNTIME_SELECTION_SOURCE_METADATA_KEY) not in _STICKY_SOURCES:
        return ""
    return str(metadata.get("runtime_target_id") or "").strip()


NO_ALLOWED_RUNTIME_DETAIL = (
    "No active runtime is allowed for this Workspace. An administrator must select an active runtime "
    "for the Workspace or enable one of its selected runtimes."
)


async def require_allowed_active_runtime(db: AsyncSession, workspace_execution_view: dict | None) -> None:
    """Refuse a ``selected_only`` Workspace whose list names no active runtime target."""
    if runtime_assignment_mode(workspace_execution_view) != "selected_only":
        return
    allowed = selected_runtime_target_ids(workspace_execution_view)
    if not any(str(target.id) in allowed for target in await get_runtime_targets(db, active_only=True)):
        raise TurnRefusedError(TurnRefusalState.RUNTIME_NOT_ALLOWED, NO_ALLOWED_RUNTIME_DETAIL)


def _requirement_unmet(detail: str) -> TurnRefusedError:
    return TurnRefusedError(TurnRefusalState.RUNTIME_REQUIREMENT_UNMET, detail)


async def load_turn_selection(
    db: AsyncSession, workspace_execution_view: dict | None, session: AgentSession | None
) -> tuple[SelectionSnapshot, WorkspaceScope]:
    """The catalog/order snapshot and the Workspace scope (allowlist, explicit default, data class)."""
    workspace_id = str((normalize_workspace_execution_view(workspace_execution_view) or {}).get("workspace_id") or "")
    metadata = dict(session.metadata_ or {}) if session is not None else None
    scope = await load_scope(db, workspace_id=workspace_id, view=workspace_execution_view, session_metadata=metadata)
    return await load_snapshot(db), scope


async def resolve_turn_runtime(
    db: AsyncSession,
    choice: RuntimeChoice,
    *,
    runtime_target_id_explicit: bool,
    session: AgentSession | None,
    workspace_execution_view: dict | None,
    agent_runtime_target_id: str | None,
    workflow_contract: dict[str, Any] | None,
) -> None:
    """Settle ``choice`` by the closed precedence (see the module docstring)."""
    await require_allowed_active_runtime(db, workspace_execution_view)
    try:
        capability = required_model_capability(workflow_contract)
    except UnsupportedModelCapabilityError as error:
        raise _requirement_unmet(f"The selected workflow requires an unsupported model capability: {error}.") from None
    snapshot, scope = await load_turn_selection(db, workspace_execution_view, session)

    def refusal(runtime_target_id: str) -> str:
        return gate(snapshot.for_target(runtime_target_id), scope, capability=capability)

    if runtime_target_id_explicit and choice.runtime_target_id:
        reason = refusal(choice.runtime_target_id)
        if reason == REASON_CAPABILITY:
            raise _requirement_unmet(
                f"The selected runtime does not meet the workflow's required model capability '{capability}'."
            )
        if reason:
            raise TurnRefusedError(TurnRefusalState.RUNTIME_NOT_ALLOWED, f"The chosen model cannot answer here. "
                                   f"{reason_text(reason)}")
        return
    session_runtime_target_id = _session_runtime_target_id(session)
    if session_runtime_target_id in choice.labels and session_runtime_target_id:
        require_runtime_allowed(workspace_execution_view, runtime_target_id=session_runtime_target_id)
    implicit = (
        (RuntimeSelectionSource.SESSION, session_runtime_target_id),
        (RuntimeSelectionSource.AGENT, str(agent_runtime_target_id or "").strip()),
    )
    for source, runtime_target_id in implicit:
        if runtime_target_id and runtime_target_id in choice.labels and not refusal(runtime_target_id):
            choice.choose(runtime_target_id, source)
            return
    if capability:
        for key in snapshot.order:
            model = snapshot.model(key)
            if model is None or gate(model, scope, capability=capability):
                continue
            picked = next((target_id for target_id in model.target_ids if target_id in choice.labels), "")
            if picked:
                choice.choose(picked, RuntimeSelectionSource.WORKFLOW)
                return
        raise _requirement_unmet(
            f"No active runtime allowed for this Workspace meets the workflow's required model capability "
            f"'{capability}'. Configure a capable runtime."
        )
    workspace_default = scope.default_target_id
    if workspace_default and not refusal(workspace_default):
        choice.choose(workspace_default, RuntimeSelectionSource.WORKSPACE_DEFAULT)
        return
    choice.choose("", RuntimeSelectionSource.GLOBAL_DEFAULT)


__all__ = [
    "NO_ALLOWED_RUNTIME_DETAIL",
    "RUNTIME_SELECTION_SOURCE_METADATA_KEY",
    "RuntimeChoice",
    "RuntimeSelectionSource",
    "initial_runtime_choice",
    "load_turn_selection",
    "require_allowed_active_runtime",
    "require_runtime_allowed",
    "resolve_turn_runtime",
    "sticky_session_runtime_target_id",
]
