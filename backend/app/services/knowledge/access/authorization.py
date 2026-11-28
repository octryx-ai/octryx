"""Workspace authorization for the Evidence ledger. Unknown, foreign and malformed Workspaces raise one error; the
project row is checked before the role."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, User
from ...access_control import get_project_role_for_user
from ..identity.workspace import WorkspaceId
from ..ledger.errors import WorkspaceNotAccessibleError
from ..retrieval.errors import KnowledgeRetrievalError
from .acl_keys import AclKey, PrincipalKey, query_acl_keys, reader_principal_keys

WORKSPACE_WRITE_FORBIDDEN_DETAIL = "Project admin or owner role required for this action."
AUTHOR_PROJECT_ROLES = frozenset({"admin", "owner"})


BOUND_READER_ROLE = "bound_reader"


@dataclass(frozen=True, slots=True)
class AuthorizedWorkspace:
    # A bound read keeps the user's principal keys: the reader Workspace changes, the person does not.
    workspace: WorkspaceId
    project_id: str
    role: str
    on_behalf_of: str | None = None
    principal_keys: tuple[PrincipalKey, ...] = ()

    @property
    def may_author(self) -> bool:
        return self.on_behalf_of is None and self.role in AUTHOR_PROJECT_ROLES

    @property
    def acl_keys(self) -> tuple[AclKey, ...]:
        return query_acl_keys(self.principal_keys)

    @property
    def admission_project_id(self) -> str:
        return self.on_behalf_of or self.project_id


class WorkspaceWriteForbiddenError(Exception):
    def __init__(self) -> None:
        super().__init__(WORKSPACE_WRITE_FORBIDDEN_DETAIL)


def parse_workspace_id(raw: object) -> WorkspaceId:
    try:
        return WorkspaceId.parse(raw)
    except KnowledgeRetrievalError:
        # Raised outside the handler so no contract error is chained, and so a
        # malformed id is indistinguishable from a foreign one.
        pass
    raise WorkspaceNotAccessibleError()


async def authorize_workspace(
    db: AsyncSession,
    *,
    current_user: User,
    workspace_id: object,
    require_author: bool = False,
) -> AuthorizedWorkspace:
    workspace = parse_workspace_id(workspace_id)
    project_id = workspace.canonical
    project = (await db.execute(select(Project.id).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        # Checked before the role: a global admin would otherwise resolve a role
        # for a Workspace that does not exist.
        raise WorkspaceNotAccessibleError()
    role = await get_project_role_for_user(db, current_user.id, project_id)
    if role is None:
        raise WorkspaceNotAccessibleError()
    authorized = AuthorizedWorkspace(
        workspace=workspace,
        project_id=project_id,
        role=str(role),
        principal_keys=reader_principal_keys(current_user),
    )
    if require_author and not authorized.may_author:
        raise WorkspaceWriteForbiddenError()
    return authorized


async def authorize_tool_workspace(
    db: AsyncSession,
    *,
    user_id: str,
    project_id: object,
    allowed_project_ids: object,
) -> AuthorizedWorkspace:
    # The Workspace comes from ToolContext only, never from a model argument.
    workspace = parse_workspace_id(project_id)
    canonical = workspace.canonical
    allowed = allowed_project_ids if isinstance(allowed_project_ids, list | tuple | set | frozenset) else ()
    if canonical not in {str(item) for item in allowed}:
        raise WorkspaceNotAccessibleError()
    project = (await db.execute(select(Project.id).where(Project.id == canonical))).scalar_one_or_none()
    if project is None:
        raise WorkspaceNotAccessibleError()
    role = await get_project_role_for_user(db, str(user_id), canonical)
    if role is None:
        raise WorkspaceNotAccessibleError()
    user = await db.get(User, str(user_id))
    return AuthorizedWorkspace(
        workspace=workspace, project_id=canonical, role=str(role), principal_keys=reader_principal_keys(user)
    )
