"""A DAG flow run starts in a Workspace, like a workflow run.

Every public DAG start (a version run, a partial run, a flow test case run and a published workflow capability run,
from its route or as a tool call) resolves its Workspace before any session, audit start or run row is written, with
the workflow-run start contract (``workflow_runs.access.require_start_scope``): none, an unknown one, or one outside
the starter's scope is ``needs_configuration`` / ``workspace_required``; an inactive one is ``workspace_inactive``.
The refusal is a ``WorkflowRunError``; a route answers it with ``_workflow_run_http._http``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..workflow_runs.access import (
    UNRESOLVED_WORKSPACE_MESSAGE,
    require_start_scope,
    require_start_workspace,
    workspace_required_error,
)


async def require_flow_start_workspace(db: AsyncSession, user_id: str, project_id: str | None) -> None:
    """Refuse a DAG flow start that has no Workspace the starter may start in (see the module docstring)."""
    require_start_workspace(project_id, None)
    user = await db.get(User, user_id)
    if user is None:  # no starter whose scope could hold the Workspace
        raise workspace_required_error(UNRESOLVED_WORKSPACE_MESSAGE)
    await require_start_scope(db, user, project_id=project_id, item=None)


__all__ = ["require_flow_start_workspace"]
