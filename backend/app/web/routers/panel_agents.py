"""Auto-extracted router module: panel_agents."""

# ruff: noqa: F821, I001, E501
from fastapi import APIRouter

from app.db import get_db
from app.schemas.admin.admin_panel._agents import (
    AgentCreateRequest,
    AgentGroupCreateRequest,
    AgentGroupUpdateRequest,
    AgentStepCreateRequest,
    AgentStepUpdateRequest,
    AgentUpdateRequest,
)
from app.schemas.admin.admin_runtime_panel import ReorderRequest
from app.services.admin.governance.admin_agent_service import (
    create_agent as admin_create_agent,
    create_agent_step as admin_create_agent_step,
    delete_agent as admin_delete_agent,
    delete_agent_step as admin_delete_agent_step,
    reorder_agent_steps as admin_reorder_agent_steps,
    update_agent as admin_update_agent,
    update_agent_step as admin_update_agent_step,
)
from app.services.admin.governance._admin_agent_meta import (
    build_agent_builder_meta,
    list_agent_definitions as admin_list_agent_definitions,
)
from app.services.agent_group import (
    create_agent_group as admin_create_agent_group,
    delete_agent_group as admin_delete_agent_group,
    list_agent_groups as admin_list_agent_groups,
    serialize_agent_group,
    update_agent_group as admin_update_agent_group,
)
from app.services.platform_agents.overview import platform_agents_overview
from app.services.agent_usage import USAGE_WINDOW_DAYS, agent_usage_counts
from app.services.agent_references import list_agent_references
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.auth import THINKING_LEVELS
from app.services.runtime_options import list_chat_runtime_options
from app.services.agent_definition_payload import serialize_agent_definition_payload
from app.services.agent_definition_payload import serialize_agent_step_payload
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ...services.access_control import require_existing_workspace


router = APIRouter()


def _tool_options() -> list[str]:
    from app.services.agent_definition_validation_steps import known_tool_names

    return sorted(known_tool_names())


@router.get("/chat/api/panel/agents")
async def panel_list_agents(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    agents = await admin_list_agent_definitions(db, user_id=user.id)
    return JSONResponse([serialize_agent_definition_payload(agent) for agent in agents])


@router.get("/chat/api/panel/agents/overview")
async def panel_agents_overview(request: Request, db: AsyncSession = Depends(get_db)):
    """The Agents page extras (A3): built-ins shipped in code and usage in the last 30 days."""
    await _require_admin_api(request, db)
    return JSONResponse({
        # The platform agents replace the listed built-ins (Assistant, Engineer, Reviewer).
        "builtins": await platform_agents_overview(db),
        "usage_window_days": USAGE_WINDOW_DAYS,
        "usage": await agent_usage_counts(db),
    })


@router.get("/chat/api/panel/agent-groups")
async def panel_list_agent_groups(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    groups = await admin_list_agent_groups(db, user_id=user.id)
    return JSONResponse([serialize_agent_group(group) for group in groups])


@router.post("/chat/api/panel/agent-groups")
async def panel_create_agent_group(
    payload: AgentGroupCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(await admin_create_agent_group(db, user_id=user.id, payload=payload.model_dump()))


@router.put("/chat/api/panel/agent-groups/{group_id}")
async def panel_update_agent_group(
    group_id: str,
    payload: AgentGroupUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.project_id)
    return JSONResponse(
        await admin_update_agent_group(
            db, user_id=user.id, group_id=group_id, payload=payload.model_dump(exclude_none=True)
        )
    )


@router.delete("/chat/api/panel/agent-groups/{group_id}")
async def panel_delete_agent_group(group_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_agent_group(db, user_id=user.id, group_id=group_id))


@router.get("/chat/api/panel/agents/meta")
async def panel_agent_builder_meta(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    runtime_options = await list_chat_runtime_options(db)
    return JSONResponse(
        await build_agent_builder_meta(
            db,
            user_id=user.id,
            runtime_options=runtime_options,
            thinking_levels=THINKING_LEVELS,
            tool_options=_tool_options(),
        )
    )


@router.post("/chat/api/panel/agents")
async def panel_create_agent(
    payload: AgentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_create_agent(
            db,
            user_id=user.id,
            payload=payload.model_dump(),
            thinking_levels=THINKING_LEVELS,
            serialize_agent_definition=serialize_agent_definition_payload,
        )
    )


@router.put("/chat/api/panel/agents/{agent_id}")
async def panel_update_agent(
    agent_id: str,
    payload: AgentUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_agent(
            db,
            user_id=user.id,
            agent_id=agent_id,
            payload=payload.model_dump(exclude_none=True),
            thinking_levels=THINKING_LEVELS,
            serialize_agent_definition=serialize_agent_definition_payload,
        )
    )


@router.get("/chat/api/panel/agents/{agent_id}/references")
async def panel_agent_references(agent_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await list_agent_references(db, user=user, agent_id=agent_id))


@router.delete("/chat/api/panel/agents/{agent_id}")
async def panel_delete_agent(agent_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_agent(db, user_id=user.id, agent_id=agent_id))


@router.post("/chat/api/panel/agents/{agent_id}/steps")
async def panel_create_agent_step(
    agent_id: str,
    payload: AgentStepCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_create_agent_step(
            db,
            user_id=user.id,
            agent_id=agent_id,
            payload=payload.model_dump(),
            serialize_agent_step=serialize_agent_step_payload,
        )
    )


@router.put("/chat/api/panel/agents/{agent_id}/steps/{step_id}")
async def panel_update_agent_step(
    agent_id: str,
    step_id: str,
    payload: AgentStepUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_update_agent_step(
            db,
            user_id=user.id,
            agent_id=agent_id,
            step_id=step_id,
            payload=payload.model_dump(exclude_none=True),
            serialize_agent_step=serialize_agent_step_payload,
        )
    )


@router.delete("/chat/api/panel/agents/{agent_id}/steps/{step_id}")
async def panel_delete_agent_step(agent_id: str, step_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    return JSONResponse(await admin_delete_agent_step(db, user_id=user.id, agent_id=agent_id, step_id=step_id))


@router.post("/chat/api/panel/agents/{agent_id}/steps/reorder")
async def panel_reorder_agent_steps(
    agent_id: str,
    payload: ReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    return JSONResponse(
        await admin_reorder_agent_steps(
            db,
            user_id=user.id,
            agent_id=agent_id,
            order=payload.order,
            serialize_agent_step=serialize_agent_step_payload,
        )
    )
