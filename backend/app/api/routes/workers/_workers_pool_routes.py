from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....schemas.operations.worker import (
    TaskRoutingRuleCreateRequest,
    TaskRoutingRuleResponse,
    WorkerCapacityLogResponse,
    WorkerDomainExpertiseResponse,
    WorkerDomainExpertiseUpsertRequest,
    WorkerPoolConfigResponse,
    WorkerPoolConfigUpdateRequest,
    WorkerRateLimitResponse,
    WorkerRateLimitUpdateRequest,
)
from ....services.access_control import require_visible_workspace
from ....services.auth import get_current_user
from ....services.auth.admin_principal import get_current_admin_user
from ....services.worker_pool_service import (
    create_task_routing_rule,
    evaluate_pool_scaling,
    get_pool_config,
    get_project_rate_limit,
    list_task_routing_rules,
    list_worker_capacity_logs,
    list_worker_domain_expertise,
    update_pool_config,
    update_project_rate_limit,
    upsert_worker_domain_expertise,
)

router = APIRouter()


@router.get("/projects/{project_id}/pool-config", response_model=WorkerPoolConfigResponse)
async def get_project_pool_config(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await get_pool_config(db, project_id=project_id, current_user=current_user)


@router.put("/projects/{project_id}/pool-config", response_model=WorkerPoolConfigResponse)
async def put_project_pool_config(
    project_id: str,
    body: WorkerPoolConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await update_pool_config(
        db,
        project_id=project_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/projects/{project_id}/rate-limits", response_model=WorkerRateLimitResponse)
async def get_project_worker_rate_limit(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await get_project_rate_limit(db, project_id=project_id, current_user=current_user)


@router.put("/projects/{project_id}/rate-limits", response_model=WorkerRateLimitResponse)
async def put_project_worker_rate_limit(
    project_id: str,
    body: WorkerRateLimitUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await update_project_rate_limit(
        db,
        project_id=project_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.get("/projects/{project_id}/routing-rules", response_model=list[TaskRoutingRuleResponse])
async def get_project_task_routing_rules(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await list_task_routing_rules(db, project_id=project_id, current_user=current_user)


@router.post("/projects/{project_id}/routing-rules", response_model=TaskRoutingRuleResponse)
async def post_project_task_routing_rule(
    project_id: str,
    body: TaskRoutingRuleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    return await create_task_routing_rule(
        db,
        project_id=project_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )


@router.post("/projects/{project_id}/autoscale/run", response_model=dict)
async def post_project_worker_autoscale_run(
    project_id: str,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, project_id)
    summary = await evaluate_pool_scaling(db, project_id=project_id)
    await db.commit()
    return summary


@router.get("/{worker_id}/capacity-log", response_model=list[WorkerCapacityLogResponse])
async def get_worker_capacity_log(
    worker_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_capacity_logs(db, worker_id=worker_id, current_user=current_user, limit=limit)


@router.get("/{worker_id}/expertise", response_model=list[WorkerDomainExpertiseResponse])
async def get_worker_expertise(
    worker_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_worker_domain_expertise(db, worker_id=worker_id, current_user=current_user)


@router.post("/{worker_id}/expertise", response_model=WorkerDomainExpertiseResponse)
async def post_worker_expertise(
    worker_id: str,
    body: WorkerDomainExpertiseUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await upsert_worker_domain_expertise(
        db,
        worker_id=worker_id,
        current_user=current_user,
        payload=body.model_dump(exclude_unset=True),
    )
