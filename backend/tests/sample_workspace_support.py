"""The sample Workspace ``acme-orders`` and its Document Updater agent that the test baseline seeds."""

# ruff: noqa: E501

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition, AgentStep, Project, User, UserProject
from app.services.agent_definition_authoring import governs_agent_definition_write
from app.services.agent_definition_writers import AgentDefinitionWriter
from app.services.prompt_catalog.seeding import ensure_prompt_catalog_seed
from app.services.trace_capture import ensure_default_trace_capture_config

DOCUMENT_UPDATER_DEFINITION: dict[str, object] = {
    "name": "Document Updater",
    "description": "Analyzes the latest code changes and prepares targeted documentation updates for Confluence.",
    "goal": "Understand the latest code changes, derive the documentation needs, and update or draft the necessary "
    "Confluence changes.",
    "agent_type": "change",
    "thinking_level": "deep",
    "branch_prefix": "octryx",
    "steps": [
        {
            "name": "Collect changes",
            "step_type": "analysis",
            "instructions": "Fetch the relevant commits or pull requests for the requested period or branch. "
            "Prepare the affected repository if needed and determine the concrete code or "
            "configuration changes. Add Jira context if needed.",
            "success_criteria": "The relevant technical changes, affected components and concrete file changes are "
            "clearly identified.",
            "allowed_tools": [
                "list_recent_bitbucket_commits",
                "search_jira_tickets",
                "prepare_bitbucket_repository",
                "git_change_summary",
                "list_workspace_git_commits",
                "analyze_workspace_repository",
            ],
        },
        {
            "name": "Derive documentation needs",
            "step_type": "documentation",
            "instructions": "Check which runbooks, architecture or operations notes in Confluence are affected and "
            "whether there are knowledge gaps. Use the Confluence search instead of guessing page "
            "IDs or titles.",
            "success_criteria": "It is clear which pages are to be updated, created or left unchanged, and the "
            "concrete target pages are identified.",
            "allowed_tools": ["knowledge_search", "search_confluence", "list_confluence_pages", "get_confluence_page"],
        },
        {
            "name": "Update Confluence",
            "step_type": "change",
            "instructions": "Apply the necessary changes to the Confluence pages already identified, precisely and "
            "traceably. Use the page lists or concrete page contents from the previous step "
            "instead of starting a new broad search. If no content change is needed, end the step "
            "with a clear justification.",
            "success_criteria": "The affected pages were updated, or there is a clear justification why no change "
            "was possible.",
            "allowed_tools": [
                "list_confluence_pages",
                "get_confluence_page",
                "update_confluence_page",
                "create_confluence_page",
            ],
        },
    ],
    "system_prompt": "Work documentation-first. Link code, ticket and Confluence context cleanly and do not propose "
    "speculative documentation changes.",
    "output_prompt": "Answer with: 1. changed scope, 2. affected Confluence pages, 3. proposed or applied "
    "documentation change, 4. open questions.",
}

AgentStepSpec = tuple[str, str, str, str, list[str]]


async def sync_agent_steps(
    db: AsyncSession,
    *,
    agent_id: str,
    step_specs: list[AgentStepSpec],
    delete_extra_steps: bool,
) -> None:
    existing_steps = (
        (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id).order_by(AgentStep.position.asc())))
        .scalars()
        .all()
    )
    for position, step_spec in enumerate(step_specs, start=1):
        name, step_type, instructions, success_criteria, allowed_tools = step_spec
        step = existing_steps[position - 1] if position - 1 < len(existing_steps) else None
        if step is None:
            step = AgentStep(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                position=position,
            )
            db.add(step)
        step.position = position
        step.name = name
        step.step_type = step_type
        step.instructions = instructions
        step.success_criteria = success_criteria
        step.allowed_tools = allowed_tools
        step.is_enabled = True

    if not delete_extra_steps:
        return

    for step in existing_steps[len(step_specs) :]:
        await db.delete(step)


def _build_step_specs(step_definitions: list[dict[str, object]]) -> list[tuple[str, str, str, str, list[str]]]:
    step_specs: list[tuple[str, str, str, str, list[str]]] = []
    for step_definition in step_definitions:
        step_specs.append(
            (
                str(step_definition.get("name") or "").strip(),
                str(step_definition.get("step_type") or "").strip(),
                str(step_definition.get("instructions") or "").strip(),
                str(step_definition.get("success_criteria") or "").strip(),
                [str(tool) for tool in step_definition.get("allowed_tools") or []],
            )
        )
    return step_specs


# The test baseline seeds through a bootstrap writer, so the sample definitions get a published revision 1.
@governs_agent_definition_write(AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS, actor_param="admin_user")
async def ensure_sample_workspace_bootstrap(db: AsyncSession, *, admin_user: User) -> None:
    project = await _ensure_acme_orders_project(db, admin_user=admin_user)
    await ensure_prompt_catalog_seed(db, admin_user=admin_user)
    await _ensure_document_updater(
        db,
        admin_user_id=admin_user.id,
        project_id=project.id,
        definition=DOCUMENT_UPDATER_DEFINITION,
    )


async def _ensure_acme_orders_project(db: AsyncSession, *, admin_user: User) -> Project:
    result = await db.execute(select(Project).where(Project.name == "acme-orders"))
    acme_orders_project = result.scalar_one_or_none()

    if not acme_orders_project:
        acme_orders_project = Project(
            id=str(uuid.uuid4()),
            name="acme-orders",
            description="Acme Orders project for operational knowledge, repositories and documentation mapping",
            config=ensure_default_trace_capture_config(
                {
                    "confluence_space_key": "INFRA",
                    "confluence_root_page_id": "100101",
                    "project_slug": "acme-orders",
                    "managed_repo_root": "var/repos/bitbucket",
                }
            ),
            is_active=True,
        )
        db.add(acme_orders_project)
        await db.flush()
        db.add(UserProject(user_id=admin_user.id, project_id=acme_orders_project.id, role="owner"))
        return acme_orders_project

    acme_orders_project.config = ensure_default_trace_capture_config(
        {
            **(acme_orders_project.config or {}),
            "managed_repo_root": "var/repos/bitbucket",
            "project_slug": "acme-orders",
            "confluence_space_key": "INFRA",
            "confluence_root_page_id": "100101",
        }
    )
    return acme_orders_project


async def _ensure_sample_agent(
    db: AsyncSession,
    *,
    admin_user_id: str,
    project_id: str,
    definition: dict[str, object],
    default_name: str,
) -> AgentDefinition:
    name = str(definition.get("name") or default_name).strip() or default_name
    result = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.owner_id == admin_user_id,
            AgentDefinition.name == name,
        )
    )
    agent = result.scalar_one_or_none()
    description = str(definition.get("description") or "").strip()
    goal = str(definition.get("goal") or "").strip()
    agent_type = str(definition.get("agent_type") or "change").strip() or "change"
    thinking_level = str(definition.get("thinking_level") or "deep").strip() or "deep"
    branch_prefix = str(definition.get("branch_prefix") or "octryx").strip() or "octryx"
    system_prompt = str(definition.get("system_prompt") or "").strip()
    output_prompt = str(definition.get("output_prompt") or "").strip()
    require_self_review = bool(definition.get("require_self_review"))
    step_specs = _build_step_specs(list(definition.get("steps") or []))

    if not agent:
        agent = AgentDefinition(
            id=str(uuid.uuid4()),
            owner_id=admin_user_id,
            project_id=project_id,
            name=name,
            description=description,
            goal=goal,
            agent_type=agent_type,
            thinking_level=thinking_level,
            branch_prefix=branch_prefix,
            system_prompt=system_prompt,
            output_prompt=output_prompt,
            require_self_review=require_self_review,
            is_active=True,
        )
        db.add(agent)
        await db.flush()

    agent.project_id = project_id
    agent.description = description
    agent.goal = goal
    agent.agent_type = agent_type
    agent.thinking_level = thinking_level
    agent.branch_prefix = branch_prefix
    agent.system_prompt = system_prompt
    agent.output_prompt = output_prompt
    agent.require_self_review = require_self_review
    agent.is_active = True

    await sync_agent_steps(
        db,
        agent_id=agent.id,
        step_specs=step_specs,
        delete_extra_steps=True,
    )
    return agent


async def _ensure_document_updater(
    db: AsyncSession,
    *,
    admin_user_id: str,
    project_id: str,
    definition: dict[str, object],
) -> None:
    await _ensure_sample_agent(
        db,
        admin_user_id=admin_user_id,
        project_id=project_id,
        definition=definition,
        default_name="Document Updater",
    )
