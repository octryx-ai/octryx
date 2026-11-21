import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.core.prompts.prompt_templates import ensure_system_prompt_variant_routing
from app.models import AgentDefinition, Project, User, UserProject
from app.services.agent_definition_authoring import governs_agent_definition_write
from app.services.agent_definition_writers import AgentDefinitionWriter
from app.services.prompt_catalog.seeding import ensure_prompt_catalog_seed
from app.services.sample_workspace_bootstrap.agent_steps import sync_agent_steps
from app.services.trace_capture import ensure_default_trace_capture_config

from .sample_agents import DOCUMENT_UPDATER_DEFINITION


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


@governs_agent_definition_write(
    AgentDefinitionWriter.BOOTSTRAP_SAMPLE_WORKSPACE, actor_param="admin_user"
)
async def ensure_sample_workspace_bootstrap(db: AsyncSession, *, admin_user: User) -> None:
    project = await _ensure_acme_orders_project(db, admin_user=admin_user)
    await ensure_system_prompt_variant_routing(db)
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
