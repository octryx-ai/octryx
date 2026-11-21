"""Preparation stages that plan the turn's context and resolve its knowledge and grounding prompts."""

from __future__ import annotations

from app.services.agent_tool_surface_contract import denies_tools

from ....services.context_checkpoint import (
    get_active_context_checkpoint,
    render_context_checkpoint_for_prompt,
)
from ....services.engineering_knowledge.runtime_prompt_renderer import resolve_engineering_knowledge_runtime_prompt
from ....services.knowledge.access.source_context import build_repository_source_context
from ....services.prompt_catalog import render_prompt
from ....services.scenario_profile import apply_scenario_profile, resolve_scenario_profile
from ....services.session.entity import list_session_entities, render_session_entities_for_prompt
from ....services.workflow_runs.phase_workspace import RUN_WORKING_COPY_KEY
from ..prompts.prompt_builder import (
    build_minimal_personality_prompt,
    build_personality_prompt,
    build_skill_discovery_prompt,
)
from .context_planner import plan_turn_context
from .evidence_grounding import render_evidence_grounding_prompt, resolve_evidence_grounding_policy
from .repo_context import load_repo_context_prompts
from .run_context_prompt_policy import compose_memory_prompt
from .run_context_state import AgentRunRequest, RunPreparation
from .workspace_scopes_prompt import workspace_scopes_prompt


async def plan_context(request: AgentRunRequest, state: RunPreparation) -> None:
    """Plan the context tier and budget, then the personality and skills prompts that follow from it."""
    db, capability_type, agent_definition = request.db, state.capability_type, request.agent_definition
    # The prompt is not a planning input: tier, sections and budget come from explicit inputs.
    context_plan = plan_turn_context(
        capability_type=capability_type,
        is_change_mode=capability_type == "change",
        project_id=request.project_id,
        agent_definition=agent_definition,
        session_metadata=state.session_metadata,
        history_count=len(state.all_history),
    )
    scenario_profile = await resolve_scenario_profile(
        db,
        owner_id=request.user_id,
        project_id=request.project_id,
        context_plan=context_plan,
    )
    context_plan = apply_scenario_profile(context_plan, scenario_profile)
    state.context_plan = context_plan
    state.scenario_budget_override = (
        "token_budget" in (scenario_profile.planner_config or {}) if scenario_profile else False
    )
    state.model_context_cap = await request.resolve_model_context_cap(db, runtime_target_id=request.runtime_target_id)

    # Without saved preferences the answer still follows the person's language.
    personality = state.personality
    personality_prompt = build_personality_prompt(personality) if personality else render_prompt(
        "personality.language.en")
    if context_plan.tier == "minimal":
        personality_prompt = build_minimal_personality_prompt(personality_prompt)
    state.personality_prompt = personality_prompt

    # Session memory is the Knowledge Memory lobe: the agent recalls it explicitly (``memory_recall``);
    # nothing from session memory is injected into the prompt.

    # Skills are reached through skill_search/skill_get, which a text-only agent does not have.
    state.skills_prompt = (
        build_skill_discovery_prompt() if context_plan.include_skills and not denies_tools(agent_definition) else ""
    )


async def resolve_knowledge_and_entities(request: AgentRunRequest, state: RunPreparation) -> None:
    """Resolve the engineering-pack prompt, the session entities, the Workspace scopes and the checkpoint."""
    db, project_id, session_metadata = request.db, request.project_id, state.session_metadata
    # No Knowledge entry is injected: governed Knowledge is recalled through ``knowledge_search``.
    # Only the engineering-pack runtime resolution below contributes a prompt fragment.
    _agent_step_tools: set[str] = {
        str(tool).strip()
        for step in (request.agent_definition or {}).get("steps", [])
        if step.get("isEnabled") or step.get("is_enabled")
        for tool in (step.get("allowedTools") or step.get("allowed_tools") or [])
        if str(tool).strip()
    }
    _agent_owns_pack_build = bool(_agent_step_tools & {"engineering_pack_search", "pack_draft_create"})
    engineering_runtime_prompt, engineering_runtime_metadata = await resolve_engineering_knowledge_runtime_prompt(
        db=db,
        project_id=project_id,
        session_metadata=session_metadata,
    )
    state.engineering_runtime_metadata = engineering_runtime_metadata
    if engineering_runtime_prompt and not _agent_owns_pack_build:
        state.engineering_knowledge_prompt = engineering_runtime_prompt
    if engineering_runtime_metadata:
        session_metadata["engineering_knowledge_runtime_resolution"] = engineering_runtime_metadata
        if state.current_session is not None:
            state.current_session.metadata_ = session_metadata
            await db.flush()
    # The stored relevance order bounds the entities; the prompt's wording does not filter them.
    state.session_entities = await list_session_entities(db, session_id=request.session_id, limit=12)
    entity_context_prompt = render_session_entities_for_prompt(state.session_entities)
    # The connected Jira projects, Confluence spaces and repositories, so the model names the right targets.
    workspace_scopes = await workspace_scopes_prompt(db, project_id)
    state.entity_context_prompt = "\n\n".join(part for part in (workspace_scopes, entity_context_prompt) if part)
    active_context_checkpoint = await get_active_context_checkpoint(db, session_id=request.session_id)
    state.checkpoint_context_prompt = render_context_checkpoint_for_prompt(active_context_checkpoint)


async def _load_repository_prompts(request: AgentRunRequest, state: RunPreparation) -> None:
    project_config = state.project_config
    state.repo_microagents_prompt, repo_knowledge_prompt = await load_repo_context_prompts(
        workspace_root=str(state.tool_workspace_root),
        project_config=project_config,
        capability_type=state.capability_type,
    )
    # A phase reading the run's working copy is never told to use the Knowledge snapshot instead of a checkout.
    repository_sources_prompt = ""
    if not project_config.get(RUN_WORKING_COPY_KEY):
        repository_sources_prompt = await build_repository_source_context(
            request.db, user_id=request.user_id, workspace_id=request.project_id,
            allowed_project_ids=state.user_project_ids,
        )
    state.repo_knowledge_prompt = "\n\n".join(filter(None, (repo_knowledge_prompt, repository_sources_prompt)))


async def resolve_repository_and_grounding(request: AgentRunRequest, state: RunPreparation) -> None:
    """Load the repository prompts, resolve the evidence grounding policy and compose the memory prompt."""
    await _load_repository_prompts(request, state)
    from app.services.system_config.evidence_domains import get_evidence_grounding_config

    db, session_metadata = request.db, state.session_metadata
    engineering_runtime_metadata = state.engineering_runtime_metadata
    evidence_grounding_config = await get_evidence_grounding_config(db)
    evidence_grounding_policy = resolve_evidence_grounding_policy(
        workflow_contract=state.strategy_decision.workflow_contract,
        agent_type=state.routing_resolution.effective_agent_type,
        project_id=request.project_id,
        project_config=state.project_config,
        high_risk_agent_types=evidence_grounding_config["high_risk_agent_types"],
        has_engineering_knowledge=bool(state.engineering_knowledge_prompt),
        has_repo_knowledge=bool(state.repo_knowledge_prompt),
        has_runtime_engineering_pack=bool(engineering_runtime_metadata.get("engineering_knowledge_pack"))
        if engineering_runtime_metadata
        else False,
    )
    state.evidence_grounding_prompt = render_evidence_grounding_prompt(evidence_grounding_policy)
    if evidence_grounding_policy.applies:
        session_metadata["evidence_grounding_policy"] = evidence_grounding_policy.to_metadata()
        if state.current_session is not None:
            state.current_session.metadata_ = session_metadata
            await db.flush()
    state.memory_prompt = compose_memory_prompt(engineering_knowledge_prompt=state.engineering_knowledge_prompt)
