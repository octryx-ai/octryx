"""Who may start, read and act on a workflow run.

The Workspace scope is the Work management one (``secure_work.access.work_scope_project_ids``: direct and
group membership; a platform admin is cross-workspace):

- **start**: a run and its Work item live in a Workspace: a start without one, or for an item without one, is refused
  for every caller as ``needs_configuration`` / ``workspace_required`` (``require_start_workspace``) before any
  scope check; the Workspace and the item must then lie in the starter's scope (a foreign item is ``work_item_scope``);
- **read**: members of the run's Workspace;
- **write** (continue a paused run, decide what it waits for): the requester, the **Work item owner** (the user
  whose account or linked accounts name the item's assignee) within the Workspace, and platform admins.
  Abort, resume in a new chat and confirmations stay the requester's (``actions``, ``hitl_decisions``); only a
  platform admin raises the loop ceiling (``api/routes/workflow_runs``). Write access is also what lets a person
  ``take_over`` the run (``responsible``);
- **decide**: a reader acts only on the decision currently offered to them, as the node's authored decider or as
  the run's **responsible person**, rechecked under the run lock.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ..access_control import WORKSPACE_NOT_FOUND_MESSAGE
from ..linked_accounts.resolution import account_identifiers
from ..secure_work.access import work_item_in_scope, work_scope_project_ids
from .records import WorkflowRunError, lock_run
from .responsible import ACTION_TAKE_OVER, is_responsible


def _in_scope(scope: set[str] | None, project_id: str | None) -> bool:
    return scope is None or (bool(project_id) and project_id in scope)


UNRESOLVED_WORKSPACE_MESSAGE = ("The named Workspace does not exist. A workflow run needs an existing Workspace: "
                                "choose one of your Workspaces and start the run again.")


def workspace_required_error(message: str | None = None) -> WorkflowRunError:
    """The typed refusal of a start without a resolved Workspace (``needs_configuration`` / ``workspace_required``):
    none named, or a named one that does not exist."""
    from ..run_admission.denials import MESSAGES, STATE_NEEDS_CONFIGURATION, WORKSPACE_REQUIRED

    return WorkflowRunError(WORKSPACE_REQUIRED, message or MESSAGES[WORKSPACE_REQUIRED], 409,
                            state=STATE_NEEDS_CONFIGURATION)


def require_start_workspace(project_id: str | None, item: WorkItem | None) -> None:
    """A run starts in a Workspace, and its Work item belongs to one. An item without a Workspace is no other
    Workspace's item, so the refusal names the missing Workspace for every caller."""
    if (item is not None and not item.project_id) or (item is None and not project_id):
        raise workspace_required_error()


async def require_start_scope(
    db: AsyncSession, user: User, *, project_id: str | None, item: WorkItem | None
) -> None:
    """Before any session or run row is written, in this precedence:

    1. no Workspace at all (none named, or an item without one): ``needs_configuration`` / ``workspace_required``;
    2. a Work item outside the caller's scope: ``work_item_scope`` (a foreign item never gets a Workspace hint);
    3. a named Workspace that does not exist or is outside the caller's scope: ``needs_configuration`` /
       ``workspace_required``, for every caller (a platform admin included), also next to an item the caller may see
       (one answer for both, so a caller never learns whether a foreign Workspace exists);
    4. a named Workspace the item does not belong to: ``work_item_scope``;
    5. an inactive Workspace: ``needs_configuration`` / ``workspace_inactive``.
    """
    from ..run_admission.denials import STATE_NEEDS_CONFIGURATION

    require_start_workspace(project_id, item)
    scope = await work_scope_project_ids(db, user)
    if item is not None and not work_item_in_scope(scope, item):
        raise WorkflowRunError("work_item_scope", "The Work item is outside your Workspace access.", 403)
    workspace = await db.get(Project, project_id) if project_id else None
    if project_id and (workspace is None or not _in_scope(scope, project_id)):
        raise workspace_required_error(UNRESOLVED_WORKSPACE_MESSAGE)
    if item is not None and item.project_id != project_id:
        raise WorkflowRunError("work_item_scope", "The Work item belongs to another Workspace.", 403)
    if workspace is not None and not workspace.is_active:
        # The model gateway refuses every call of an inactive Workspace (project_context_unresolvable): a run started
        # here could never get past its first phase, so it is refused before anything is written.
        raise WorkflowRunError("workspace_inactive",
                               f"Workspace {workspace.name} is inactive. Activate it under Admin → Workspaces.",
                               state=STATE_NEEDS_CONFIGURATION)


async def require_workspace_view(db: AsyncSession, user: User, project_id: str | None) -> None:
    if project_id and not _in_scope(await work_scope_project_ids(db, user), project_id):
        # The answer of an unknown Workspace: an outsider never learns whether a Workspace exists.
        raise WorkflowRunError("project_not_found", WORKSPACE_NOT_FOUND_MESSAGE, 404)


async def is_work_item_owner(db: AsyncSession, item: WorkItem | None, user: User) -> bool:
    """The item's assignee is the user: their username or email, or one of their linked accounts (a Jira Cloud
    assignee is an Atlassian account id, a Jira Server assignee a username)."""
    assignee = str(getattr(item, "assignee", None) or "").strip().lower()
    if not assignee:
        return False
    names = {str(user.username or "").lower(), str(user.email or "").lower()}
    names.update(await account_identifiers(db, user.id))
    return assignee in names - {""}


async def run_access(db: AsyncSession, run: WorkflowRun | None, user: User) -> str:
    """``write`` (requester, Work item owner, platform admin), ``read`` (the run's Workspace) or ``none``."""
    if run is None:
        return "none"
    if run.requested_by == user.id:
        return "write"
    scope = await work_scope_project_ids(db, user)
    if scope is None:
        return "write"
    if not _in_scope(scope, run.project_id):
        return "none"
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    return "write" if await is_work_item_owner(db, item, user) else "read"


async def require_run(db: AsyncSession, run_id: str, user: User, *, write: bool = False) -> WorkflowRun:
    """The run the user may see; with ``write`` it is also claimed (``lock_run``) and current."""
    run = await db.get(WorkflowRun, run_id)
    access = await run_access(db, run, user)
    if access == "none":
        raise WorkflowRunError("unknown_run", "The workflow run does not exist.", 404)
    if write and access != "write":
        raise WorkflowRunError("run_read_only", "Only the requester, the Work item owner or an admin acts on "
                                                "this run.", 403)
    return await lock_run(db, run) if write else run


async def require_run_action(db: AsyncSession, run_id: str, user: User, action: str) -> WorkflowRun:
    """A role grants only its current offered decision, never general Run or execution access."""
    run = await require_run(db, run_id, user)
    access = await run_access(db, run, user)
    if action == ACTION_TAKE_OVER and access != "write":
        raise WorkflowRunError("take_over_not_permitted", "Only the requester, the Work item owner or an admin "
                                                          "takes this run over.", 403)
    run = await lock_run(db, run)
    if access == "write":
        return run
    from .hitl_actions import authored_decider, decision_actions

    if not (await authored_decider(db, run) or is_responsible(run, user)):
        raise WorkflowRunError("run_read_only", "This run is read-only for you.", 403)
    offered = await decision_actions(db, run, user=user)
    if action not in {item["key"] for item in offered}:
        raise WorkflowRunError("run_read_only", "Only the current authored decision is available to you.", 403)
    # The offer is not authority: recheck current membership under the Run and membership locks.
    from .decider import require_node_decider

    await require_node_decider(db, run, user)
    return run


__all__ = ["require_run_action", "is_work_item_owner", "require_run", "require_start_scope",
           "require_workspace_view", "run_access"]
