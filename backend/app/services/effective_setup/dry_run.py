"""Dry run of the real run preparation for the Effective setup view.

The view must show what a turn gets, not a second opinion about it. So it runs the same
``prepare_agent_run`` the engine runs, for a transient session inside a savepoint that is
always rolled back: nothing it writes survives, no model is called (run preparation makes
no model call), and the turn's prompt set is bound only for the duration of the call.

"Automatic" (no key) is prepared as the explicit-mode unmatched selection: at run time the
Workspace proposal or the model's ``select_workflow`` may still pick a workflow, which a dry
run cannot know without calling a model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import AgentDefinitionResolution

from ...models import Session
from ..agent_definition_execution import resolve_agent_definition_for_execution
from ..agent_mode import DEFAULT_AGENT_MODE_KEY
from ..instructions.resolve import INSTRUCTIONS_METADATA_KEY
from ..prompt_catalog import bound_prompt_set, bound_prompt_trace_record, prompt_set_scope
from ..workflow_routing.explicit_selection import (
    explicit_mode_no_selection_resolution,
    resolve_workflow_selection_for_turn,
)
from ..workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

#: The user message of the dry run. Run preparation does not read the prompt to plan;
#: the text only fills the transient session's current turn.
DRY_RUN_MESSAGE = "Effective setup preview"
# The transient session is prepared as the chat turn it previews; it is never committed.
DRY_RUN_ORIGIN = "chat"


@dataclass(slots=True)
class SetupDryRun:
    workflow_key: str
    workflow_resolution: dict[str, Any]
    agent_resolution: AgentDefinitionResolution | None
    agent_type: str = ""
    capability_type: str = ""
    system_prompt: str = ""
    skills_prompt: str = ""
    token_budget: int = 0
    prompt_record: dict[str, Any] = field(default_factory=dict)
    #: Every catalog key under the turn's scope as a :func:`prompt_identity` (what any later render uses).
    catalog_refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    offered_tools: list[str] = field(default_factory=list)
    tool_allowlist: list[str] | None = None
    blocked_tools: list[str] = field(default_factory=list)
    tool_surface: dict[str, Any] = field(default_factory=dict)
    run_capability: dict[str, Any] = field(default_factory=dict)
    execution_profile: dict[str, Any] = field(default_factory=dict)
    instructions: list[dict[str, Any]] = field(default_factory=list)
    project_config: dict[str, Any] = field(default_factory=dict)
    agent_definition: dict[str, Any] | None = None

    @property
    def prompt_refs(self) -> dict[str, dict[str, Any]]:
        used = self.prompt_record.get("used") if isinstance(self.prompt_record, dict) else None
        return {key: prompt_identity(entry) for key, entry in (used or {}).items() if isinstance(entry, dict)}


def prompt_identity(entry: Any) -> dict[str, Any]:
    """``ref`` (key@version), ``source`` and ``digest``: a Workspace ``@1`` is not the global ``@1``."""
    if not isinstance(entry, dict):
        entry = {"ref": getattr(entry, "ref", ""), "source": getattr(entry, "source", ""),
                 "digest": getattr(entry, "digest", "")}
    return {"ref": str(entry.get("ref") or ""), "source": str(entry.get("source") or ""),
            "digest": str(entry.get("digest") or "")}


@asynccontextmanager
async def _rolled_back(db: AsyncSession) -> AsyncIterator[None]:
    """A savepoint that is always rolled back; a commit inside only flushes.

    Run preparation may commit (lazy seeding of defaults); inside a dry run that would end
    the savepoint and keep the transient session, so ``commit`` is a flush for the block.
    """
    savepoint = await db.begin_nested()
    original_commit = db.commit
    db.commit = db.flush  # type: ignore[method-assign]
    try:
        yield
    finally:
        db.commit = original_commit  # type: ignore[method-assign]
        await savepoint.rollback()


async def resolve_setup_workflow(db: AsyncSession, *, workflow_key: str, project_id: str | None) -> dict[str, Any]:
    """The workflow resolution the turn would carry, without a proposal model call."""
    clean_key = str(workflow_key or "").strip()
    if not clean_key:
        return explicit_mode_no_selection_resolution()
    return await resolve_workflow_selection_for_turn(
        db, workflow_key=clean_key, user_message=DRY_RUN_MESSAGE, project_id=project_id
    )


async def dry_run_setup(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: str | None,
    agent_id: str = "",
    workflow_key: str = "",
) -> SetupDryRun:
    """Prepare one turn for (Workspace, user, agent, workflow) and roll everything back."""
    agent_resolution = (
        await resolve_agent_definition_for_execution(db, definition_id=agent_id) if agent_id else None
    )
    agent_definition = agent_resolution.payload if agent_resolution is not None and agent_resolution.resolved else None
    # As in turn preparation: an agent brings no default workflow.
    clean_key = str(workflow_key or "").strip()
    workflow_resolution = await resolve_setup_workflow(db, workflow_key=clean_key, project_id=project_id)
    agent_type = str((agent_definition or {}).get("agentType") or "").strip() or DEFAULT_AGENT_MODE_KEY
    result = SetupDryRun(
        workflow_key=clean_key,
        workflow_resolution=workflow_resolution,
        agent_resolution=agent_resolution,
        agent_definition=agent_definition,
        agent_type=agent_type,
    )
    async with _rolled_back(db):
        session = Session(
            user_id=user_id,
            project_id=project_id or None,
            agent_type=agent_type,
            origin=DRY_RUN_ORIGIN,
            metadata_={
                ROUTING_RESOLUTION_KEY: workflow_resolution,
                "workflow_key": clean_key,
                **({"agent_definition_id": agent_id} if agent_definition else {}),
            },
        )
        db.add(session)
        await db.flush()
        prepared = await _prepare_turn(
            db, result, session=session, user_id=user_id, project_id=project_id, agent_type=agent_type,
            agent_definition=agent_definition,
        )
        _fill_from_prepared(result, prepared)
    return result


async def _prepare_turn(
    db: AsyncSession,
    result: SetupDryRun,
    *,
    session: Session,
    user_id: str,
    project_id: str | None,
    agent_type: str,
    agent_definition: dict[str, Any] | None,
) -> Any:
    """Run the engine's own run preparation for the transient session and keep the turn's prompt record."""
    from ...agent.core.context.run_context import prepare_agent_run
    from ...agent.engine import _resolve_model_context_cap
    from ...agent.engine.messages._engine_message_helpers import (
        _exclude_tool_definitions,
        _filter_tool_definitions,
        _trim_messages_to_budget,
    )
    from ..control_plane_service import resolve_control_plane_runtimes
    from ..session.workspace import get_session_workspace_root

    # The path the turn would use; nothing is created or restored on disk.
    workspace_root = await get_session_workspace_root(db, session.id, create=False)
    with prompt_set_scope(None):
        prepared = await prepare_agent_run(
            db=db,
            session_id=session.id,
            user_message=DRY_RUN_MESSAGE,
            user_id=user_id,
            project_id=project_id or None,
            agent_type=agent_type,
            runtime_target_id=None,
            thinking_level="light",
            agent_definition=agent_definition,
            parent_session_id=None,
            sub_agent_depth=0,
            workspace_root=str(workspace_root),
            resolve_model_context_cap=_resolve_model_context_cap,
            resolve_control_plane_runtimes_func=resolve_control_plane_runtimes,
            filter_tool_definitions=_filter_tool_definitions,
            exclude_tool_definitions=_exclude_tool_definitions,
            trim_messages_to_budget=_trim_messages_to_budget,
        )
        result.prompt_record = bound_prompt_trace_record() or {}
        prompt_set = bound_prompt_set()
        if prompt_set is not None:
            result.catalog_refs = {key: prompt_identity(prompt) for key, prompt in prompt_set.prompts.items()}
    return prepared


def _fill_from_prepared(result: SetupDryRun, prepared: Any) -> None:
    metadata = prepared.session_metadata
    plan = prepared.context_plan
    result.capability_type = prepared.capability_type
    result.system_prompt = prepared.system_prompt
    result.skills_prompt = prepared.skills_prompt
    result.token_budget = int(getattr(plan, "token_budget", 0) or 0)
    result.offered_tools = sorted({_tool_name(item) for item in prepared.tool_definitions} - {""})
    allowlist = getattr(plan, "tool_allowlist", None)
    result.tool_allowlist = list(allowlist) if allowlist is not None else None
    result.blocked_tools = sorted(getattr(plan, "blocked_tools", None) or [])
    result.tool_surface = {
        "source": getattr(plan, "tool_surface_source", "") or "",
        "set": getattr(plan, "tool_surface_set", "") or "",
        "include_tools": bool(getattr(plan, "include_tools", False)),
    }
    result.run_capability = dict(prepared.tool_context.run_capability or {})
    result.execution_profile = dict(metadata.get("execution_profile") or {})
    result.instructions = [dict(item) for item in metadata.get(INSTRUCTIONS_METADATA_KEY) or []]
    result.project_config = dict(prepared.tool_context.project_config or {})


def _tool_name(definition: Any) -> str:
    if isinstance(definition, dict):
        function = definition.get("function") if isinstance(definition.get("function"), dict) else {}
        return str(function.get("name") or definition.get("name") or "").strip()
    return str(getattr(definition, "name", "") or "").strip()


__all__ = ["DRY_RUN_MESSAGE", "SetupDryRun", "dry_run_setup", "prompt_identity", "resolve_setup_workflow"]
