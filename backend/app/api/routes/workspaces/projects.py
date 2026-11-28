"""Project management endpoints."""


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import Project, Role, User, UserRole
from ....schemas.core.project import (
    ProjectConfigMergeRequest,
    ProjectConfigResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from ....services.admin.project.admin_project_config_service import apply_project_config_patch
from ....services.admin.project.admin_project_config_service import (
    get_project_config_payload as admin_get_project_config_payload,
)
from ....services.admin.project.admin_project_config_service import merge_project_config as admin_merge_project_config
from ....services.auth import get_current_user
from ....services.project import get_user_project_ids
from ....services.project.default_workspace import default_workspace_id, refuse_if_default, set_default_workspace
from ....services.project_lifecycle_service import (
    archive_project_for_admin,
    create_project_for_admin,
    delete_project_for_admin,
    project_to_response,
    restore_project_for_admin,
    update_project_for_admin,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects the user has access to."""
    project_ids = await get_user_project_ids(current_user.id, db)
    if not project_ids:
        return []
    result = await db.execute(select(Project).where(Project.id.in_(project_ids), Project.is_active.is_(True)))
    projects = result.scalars().all()
    default_id = await default_workspace_id(db)
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            config=p.config or {},
            is_active=p.is_active,
            source_type=p.source_type,
            template_key=p.template_key,
            template_version=p.template_version,
            template_metadata=p.template_metadata or {},
            is_system=p.is_system,
            is_default=p.id == default_id,
        )
        for p in projects
    ]


@router.post("", response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project (admin only)."""
    await _require_admin(db, current_user, detail="Only admins can create projects")
    project = await create_project_for_admin(
        db,
        current_user=current_user,
        name=body.name,
        description=body.description,
        config=body.config,
        is_active=body.is_active,
    )
    await db.commit()
    return ProjectResponse(**project_to_response(project))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project basics and merge admin-managed config. ``config`` is a partial update like ``PUT
    /{project_id}/config``: unrelated keys are kept."""
    await _require_admin(db, current_user)
    project = await update_project_for_admin(
        db,
        project_id=project_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    if body.config is not None:
        await apply_project_config_patch(
            db,
            project=project,
            patch=body.config,
            actor_user_id=current_user.id,
        )
    await db.commit()
    return ProjectResponse(**project_to_response(project))


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive a non-system project."""
    await _require_admin(db, current_user)
    await refuse_if_default(db, project_id, "archive")
    project = await archive_project_for_admin(db, project_id=project_id)
    await db.commit()
    return ProjectResponse(**project_to_response(project))


@router.post("/{project_id}/make-default", response_model=ProjectResponse)
async def make_default_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Make an active workspace the one people start in when they have not chosen one (admin only)."""
    await _require_admin(db, current_user)
    project = await set_default_workspace(db, project_id=project_id, actor_id=current_user.id)
    await db.commit()
    return ProjectResponse(**project_to_response(project), is_default=True)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore an archived project."""
    await _require_admin(db, current_user)
    project = await restore_project_for_admin(db, project_id=project_id)
    await db.commit()
    return ProjectResponse(**project_to_response(project))


@router.delete("/{project_id}", response_model=ProjectResponse)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a non-system project."""
    await _require_admin(db, current_user)
    await refuse_if_default(db, project_id, "delete")
    project = await delete_project_for_admin(db, project_id=project_id, actor=current_user)
    await db.commit()
    return ProjectResponse(**project_to_response(project))


@router.get("/{project_id}/config", response_model=ProjectConfigResponse)
async def get_project_config(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full config dict for a project."""
    await _require_admin(db, current_user)
    return ProjectConfigResponse(**(await admin_get_project_config_payload(db, project_id=project_id)))


@router.put("/{project_id}/config", response_model=ProjectConfigResponse)
async def update_project_config(
    project_id: str,
    body: ProjectConfigMergeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Merge project settings into project.config. The body is partial: only present keys are updated."""
    await _require_admin(db, current_user)
    patch = body.model_dump(exclude_none=True)
    return ProjectConfigResponse(
        **(
            await admin_merge_project_config(
                db,
                project_id=project_id,
                patch=patch,
                actor_user_id=current_user.id,
            )
        )
    )


async def _require_admin(db: AsyncSession, current_user: User, *, detail: str = "Admin access required") -> None:
    result = await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
    )
    roles = {row[0] for row in result.all()}
    if "admin" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
