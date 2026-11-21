"""Who may write a catalog text at a scope (the workflow owner defines the flow).

- ``global``: a platform admin;
- ``workspace:<id>``: a platform admin or an owner / admin of that Workspace;
- ``workflow:<flow key>``: a platform admin or the owner (creator) of a workflow with that key.

The same rule decides who may approve a version of that scope (four eyes: the approver is another person).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.prompt_template import PROMPT_SCOPE_GLOBAL, PROMPT_SCOPE_WORKFLOW, PROMPT_SCOPE_WORKSPACE
from ..access_control import get_project_role_for_user
from ..admin.governance.admin_access_service import is_global_admin

WORKSPACE_EDITOR_ROLES = frozenset({"admin", "owner"})
OVERRIDABLE_SCOPES = frozenset({PROMPT_SCOPE_GLOBAL, PROMPT_SCOPE_WORKSPACE, PROMPT_SCOPE_WORKFLOW})


async def workflow_exists(db: AsyncSession, key: str) -> bool:
    from ...models.runtime.flow_definition import FlowDefinition

    return (await db.execute(select(FlowDefinition.id).where(FlowDefinition.key == key).limit(1))).first() is not None


async def may_write(db: AsyncSession, user_id: str, scope_type: str, scope_id: str | None) -> bool:
    if scope_type not in OVERRIDABLE_SCOPES:
        return False
    if await is_global_admin(db, user_id):
        return True
    if scope_type == PROMPT_SCOPE_WORKSPACE and scope_id:
        return await get_project_role_for_user(db, user_id, scope_id) in WORKSPACE_EDITOR_ROLES
    if scope_type == PROMPT_SCOPE_WORKFLOW and scope_id:
        from ...models.runtime.flow_definition import FlowDefinition

        owned = await db.execute(select(FlowDefinition.id).where(
            FlowDefinition.key == scope_id, FlowDefinition.created_by == user_id).limit(1))
        return owned.first() is not None
    return False


async def may_read_catalog(db: AsyncSession, user_id: str) -> bool:
    """A platform admin, an owner / admin of some Workspace, or the owner of some workflow."""
    if await is_global_admin(db, user_id):
        return True
    from ...models.runtime.flow_definition import FlowDefinition
    from ..project.service import get_project_access_details

    if any(item.get("role") in WORKSPACE_EDITOR_ROLES for item in await get_project_access_details(user_id, db)):
        return True
    return (await db.execute(select(FlowDefinition.id).where(FlowDefinition.created_by == user_id).limit(1))
            ).first() is not None


async def writable_scopes(db: AsyncSession, user_id: str) -> list[dict[str, object]]:
    """The scopes ``user_id`` may write, with labels for the editor's selector: global (platform admins), the
    Workspaces it owns or administers (every active one for an admin), the workflows it created (every one for an
    admin); ordered global, Workspaces, workflows, each by label."""
    from ...models import Project
    from ...models.runtime.flow_definition import FlowDefinition
    from ..project.service import get_project_access_details

    admin = await is_global_admin(db, user_id)
    scopes: list[dict[str, object]] = [{"scope_type": "global", "scope_id": None, "label": "Global"}] if admin else []
    if admin:
        projects = (await db.execute(select(Project.id, Project.name).where(Project.is_active.is_(True)))).all()
        workspaces = [(str(row.id), str(row.name)) for row in projects]
    else:
        workspaces = [(str(item["id"]), str(item.get("name") or item["id"]))
                      for item in await get_project_access_details(user_id, db)
                      if item.get("role") in WORKSPACE_EDITOR_ROLES]
    scopes += [{"scope_type": "workspace", "scope_id": ident, "label": name}
               for ident, name in sorted(set(workspaces), key=lambda item: item[1].lower())]
    query = select(FlowDefinition.key, FlowDefinition.name)
    if not admin:
        query = query.where(FlowDefinition.created_by == user_id)
    flows = {str(row.key): str(row.name or row.key) for row in (await db.execute(query)).all()}
    scopes += [{"scope_type": "workflow", "scope_id": key, "label": name}
               for key, name in sorted(flows.items(), key=lambda item: item[1].lower())]
    return scopes


async def owned_workflow_publish_actions(db: AsyncSession, user_id: str) -> list[str]:
    """The approval actions (``prompt_template.publish:<version>:<digest>``) of the workflow texts in review whose
    workflow ``user_id`` owns: the workflow's owner sees and decides them."""
    from ...models.runtime.flow_definition import FlowDefinition
    from ...models.runtime.governed_revision import REVISION_STATE_IN_REVIEW
    from ...models.runtime.prompt_template import PromptTemplate, PromptTemplateVersion
    from .governance import publish_approval_action

    owned = select(FlowDefinition.key).where(FlowDefinition.created_by == user_id)
    versions = (await db.execute(select(PromptTemplateVersion).join(
        PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id).where(
        PromptTemplate.scope_type == PROMPT_SCOPE_WORKFLOW, PromptTemplate.scope_id.in_(owned),
        PromptTemplateVersion.state == REVISION_STATE_IN_REVIEW))).scalars().all()
    return [publish_approval_action(version) for version in versions]


__all__ = ["OVERRIDABLE_SCOPES", "WORKSPACE_EDITOR_ROLES", "may_read_catalog", "may_write",
           "owned_workflow_publish_actions", "workflow_exists",
           "writable_scopes"]
