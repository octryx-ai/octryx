"""Workspace authorization for the Evidence ledger.

A Workspace **is** a project: the path or tool-context value is authorized as
a project first and only then parsed into a :class:`WorkspaceId` for the
knowledge layer. There is no separate tenant table and no second identity.

Indistinguishable refusals. A Workspace that does not exist, a Workspace the
caller has no role in, and a syntactically impossible Workspace id all raise the
same :class:`WorkspaceNotAccessibleError`, which the transport renders as one
fixed 404 body. A 403 is only ever returned once the caller is known to be able
to read the Workspace already and merely lacks the authoring role — the same
shape as ``services/workflow_definition_access``.

Order matters: the project row is checked *before* the role, because a global
admin resolves to the ``admin`` role for any id, including one that does not
exist. Checking the row first keeps "unknown" and "not yours" identical for
everyone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, User
from ...access_control import get_project_role_for_user
from ..identity.workspace import WorkspaceId
from ..ledger.errors import WorkspaceNotAccessibleError
from ..retrieval.errors import KnowledgeRetrievalError
from .acl_keys import query_acl_keys, reader_principal_keys

WORKSPACE_WRITE_FORBIDDEN_DETAIL = "Project admin or owner role required for this action."
AUTHOR_PROJECT_ROLES = frozenset({"admin", "owner"})


BOUND_READER_ROLE = "bound_reader"


@dataclass(frozen=True, slots=True)
class AuthorizedWorkspace:
    """A Workspace the caller is known to be able to read, and their role in it.

    ``on_behalf_of`` is set only for a read through a Workspace binding (``access/bindings.py``): it
    names the reading Workspace, whose data policy admits every remote call the read makes, because
    the query text is the reader's. Such a read never authors.

    ``principal_keys`` are the calling user's source-ACL principals (``access/acl_keys.py``).
    A bound read keeps the *user's* keys: the reader Workspace changes, the person does not. Empty
    (a caller without a user) means restricted sources stay invisible.
    """

    workspace: WorkspaceId
    project_id: str
    role: str
    on_behalf_of: str | None = None
    principal_keys: tuple[str, ...] = ()

    @property
    def may_author(self) -> bool:
        return self.on_behalf_of is None and self.role in AUTHOR_PROJECT_ROLES

    @property
    def acl_keys(self) -> tuple[str, ...]:
        """The ACL keys every query of this read admits: public spans and the user's own."""
        return query_acl_keys(self.principal_keys)

    @property
    def admission_project_id(self) -> str:
        """The Workspace whose data classification admits remote calls (embedding, rerank) for this read."""
        return self.on_behalf_of or self.project_id


class WorkspaceWriteForbiddenError(Exception):
    """The caller may read this Workspace but not add Evidence to it."""

    def __init__(self) -> None:
        super().__init__(WORKSPACE_WRITE_FORBIDDEN_DETAIL)


def parse_workspace_id(raw: object) -> WorkspaceId:
    """Parse an untrusted Workspace id; anything unusable is 'not found'."""
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
    """Authorize a Workspace for this user, or refuse indistinguishably."""
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
    """Authorize the Workspace a tool run is already scoped to.

    The Workspace comes from ``ToolContext`` only. ``allowed_project_ids`` is the
    server-owned list for the run, so even a context whose active project drifted
    cannot reach a Workspace outside the run's scope. No model argument is read
    here, by construction: this function takes no params mapping.
    """
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
