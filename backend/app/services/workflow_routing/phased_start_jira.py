"""The Jira issue of a chat's phased start: part of the same one confirmation (``phased_start``).

The rule: one confirmation per request with its scope, and everything in that scope then runs
without asking again. A request such as "create an Epic in Jira project X and have the specification
written" puts the Epic in Jira, where spec-writing then creates its stories
(``teamwork.stories``: a Jira epic gets Jira stories).

- :func:`jira_scope`: the card's "+ Jira <project>: Epic '<title>'" — for a new item, when the request names a Jira
  project, or when the Workspace is connected to Jira (one Jira intake with one project) and the workflow writes to
  Jira (a ``jira.*`` action, or ``work.create_stories``, which writes the stories under a Jira epic).
- :func:`create_jira_issue`: after Allow, the issue is created through the chat's own ``create_jira_ticket`` path:
  the confirmed card becomes the request's write plan (``chat_write_plan``: tool, fields, project scope), so the
  approval gate admits exactly this write without a second card; the issue type is normalised like every chat plan
  write. A chat that may not write through its connections gets an error, never a second card.
- :func:`jira_work_item`: the Work item is linked to the new issue the way the Jira sync stores it (source key, the
  intake's source instance), never twice: when the sync inserted the key meanwhile, that row is the item, read
  through :func:`chat_workspace_item`: a row of another Workspace answers exactly like a missing one (404).
- :func:`read_jira_issue`: an existing issue the request names by key that the Workspace's work items do
  not hold yet, read through the chat's own ``get_jira_ticket`` (a read: free, no confirmation). Without
  it an epic that lives only in Jira gets a card for a *new* Epic titled with the prompt, and Start creates a
  duplicate.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from ...models import User, WorkItem
from ...models.runtime.secure_work import WorkItemSyncConfig
from ..content_security.knowledge_fence import unfenced_result

CREATE_TOOL = "create_jira_ticket"
READ_TOOL = "get_jira_ticket"
JIRA_SOURCE = "jira"
DEFAULT_SOURCE_INSTANCE = "default"  # the connector's own entry (the default connection)
_JIRA_WRITING_ACTIONS = ("work.create_stories",)

logger = logging.getLogger(__name__)


def _text(value: Any) -> str:
    return str(value or "").strip()


def writes_jira(definition: dict[str, Any]) -> bool:
    configs = [dict(node.get("config") or {}) for node in definition.get("nodes") or [] if isinstance(node, dict)]
    actions = [_text(config.get("action") or config.get("tool")) for config in configs]
    return any(action.startswith("jira.") or action in _JIRA_WRITING_ACTIONS for action in actions)


async def _jira_intakes(db: AsyncSession, project_id: str | None) -> list[WorkItemSyncConfig]:
    if not project_id:
        return []
    return list((await db.execute(select(WorkItemSyncConfig).where(
        WorkItemSyncConfig.project_id == project_id, WorkItemSyncConfig.source_type == JIRA_SOURCE,
        WorkItemSyncConfig.is_active.is_(True)))).scalars().all())


def _project_keys(config: WorkItemSyncConfig) -> set[str]:
    return {_text(key).upper() for key in dict(config.filters_json or {}).get("project_keys") or [] if _text(key)}


async def workspace_jira_project(db: AsyncSession, project_id: str | None) -> str | None:
    """The Workspace's one Jira project (its Jira intakes name exactly one), else ``None``."""
    keys = set().union(*(_project_keys(config) for config in await _jira_intakes(db, project_id)))
    return next(iter(keys)) if len(keys) == 1 else None


async def jira_scope(db: AsyncSession, *, project_id: str | None, named_project: str | None,
                     definition: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """The Jira issue the card creates with the item, or ``None`` (see the module docstring)."""
    if item["mode"] != "new":
        return None
    source = "request" if named_project else "workspace"
    key = named_project or (await workspace_jira_project(db, project_id) if writes_jira(definition) else None)
    if not key:
        return None
    return {"project_key": key, "issue_type": item["type_label"], "summary": item["title"], "source": source,
            "label": f"+ Jira {key}: {item['type_label']} '{item['title']}'"}


def _fields(jira: dict[str, Any], description: str) -> dict[str, Any]:
    from ...tools.jira_impl._jira_issue_type_args import normalize_issue_type_args

    fields, _problem = normalize_issue_type_args({
        "project_key": jira["project_key"], "summary": jira["summary"], "description": description,
        "issue_type": jira["issue_type"], "labels": ["workflow-run"]})
    return fields


def _confirm_as_plan(session: AgentSession, fields: dict[str, Any], *, owner_id: str, approval_id: str | None) -> None:
    """The confirmed card is the request's write plan for exactly this write (``chat_write_plan``)."""
    from ..run_capability.chat_write_plan import PLAN_METADATA_KEY, current_request, merged_plan, new_plan_id

    metadata = dict(session.metadata_ or {})
    current = metadata.get(PLAN_METADATA_KEY) if isinstance(metadata.get(PLAN_METADATA_KEY), dict) else None
    metadata[PLAN_METADATA_KEY] = merged_plan(current, {
        "plan_id": new_plan_id(), "user_message_id": current_request(metadata), "request": fields["summary"],
        "writes": [{"tool": CREATE_TOOL, "connection": None, "fields": fields}],
        "scope": [{"kind": "jira_project", "value": fields["project_key"]}], "approval_id": approval_id,
    }, confirmed_by=owner_id)
    session.metadata_ = metadata


async def _chat_context(db: AsyncSession, session: AgentSession, owner_id: str) -> Any:
    """The chat turn's own tool context: its recorded class decides whether it may write through connections."""
    from ...tools.context import ToolContext
    from ..project import get_project_config
    from ..run_capability.declared import capability_from_run_profile

    config = {**await get_project_config(session.project_id, db), "project_id": session.project_id}
    capability = capability_from_run_profile(dict(session.metadata_ or {}).get("execution_profile"))
    return ToolContext(user_id=owner_id, project_ids=[session.project_id], roles=[], session_id=session.id,
                       project_config=config, db=db, run_capability=capability.tool_context_state())


async def create_jira_issue(db: AsyncSession, *, session: AgentSession, owner_id: str, jira: dict[str, Any],
                            description: str, approval_id: str | None, user_message_id: str) -> dict[str, Any]:
    """``{"key", "id"}`` of the created issue, or ``{"error": ...}``; commits the plan and its outcome.

    The held request is the request in flight again while its confirmed write runs (the plan is bound to it); the
    start's own answer ends that turn afterwards (``phased_start._post``)."""
    from ...tools import registry
    from ..run_capability.chat_writes import chat_connector_writes_enabled
    from ..session.turn_approval_state import CURRENT_TURN_USER_MESSAGE_KEY
    from ..workflow_runs.platform.dispatch import read_outcome

    fields = _fields(jira, description)
    context = await _chat_context(db, session, owner_id)
    if not chat_connector_writes_enabled(context):
        return {"error": "this chat may not write through its connections"}
    if user_message_id:
        session.metadata_ = {**dict(session.metadata_ or {}), CURRENT_TURN_USER_MESSAGE_KEY: user_message_id}
    _confirm_as_plan(session, fields, owner_id=owner_id, approval_id=approval_id)
    await db.flush()
    try:
        outcome = read_outcome(unfenced_result(await registry.execute_tool_with_plugins(CREATE_TOOL, fields, context)))
    except Exception as error:  # noqa: BLE001 - a failed Jira call is reported in the chat; the run still starts
        await db.commit()
        return {"error": f"{type(error).__name__}: {error}"[:500]}
    await db.commit()
    key = _text(outcome.result.get("ticket_id")) if outcome.ok else ""
    if not key:
        return {"error": outcome.reason or "Jira returned no issue key"}
    return {"key": key, "id": _text(outcome.result.get("id")) or None, "project_key": fields["project_key"],
            "issue_type": fields["issue_type"]}


async def jira_work_item(db: AsyncSession, *, user: User, project_id: str, item: dict[str, Any],
                         jira: dict[str, Any]) -> WorkItem:
    """The Work item of the new issue, stored like the Jira sync does; the synced row when the sync was faster."""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from ..project import get_user_project_ids
    from ..secure_work.access import WORK_ITEM_NOT_FOUND

    if project_id not in await get_user_project_ids(user.id, db):
        raise HTTPException(status_code=403, detail="User is not allowed to access this project")
    intakes = await _jira_intakes(db, project_id)
    intake = next((config for config in intakes if jira["project_key"] in _project_keys(config)),
                  intakes[0] if len(intakes) == 1 else None)
    row = WorkItem(project_id=project_id, sync_config_id=intake.id if intake else None, source_type=JIRA_SOURCE,
                   source_instance=intake.source_instance if intake else DEFAULT_SOURCE_INSTANCE,
                   source_id=jira.get("id"), source_project_key=jira["project_key"], source_key=jira["key"],
                   title=item["title"][:500], description=item["description"] or None,
                   issue_type=jira["issue_type"], reporter=user.username, work_state="intake")
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row
    except IntegrityError:
        pass
    synced = await chat_workspace_item(db, user, project_id, (await db.execute(select(WorkItem).where(
        WorkItem.source_type == JIRA_SOURCE, WorkItem.source_instance == row.source_instance,
        WorkItem.source_key == row.source_key))).scalars().first())
    if synced is None:  # missing, or another Workspace's: the same answer
        raise HTTPException(status_code=404, detail=WORK_ITEM_NOT_FOUND)
    return synced


async def chat_workspace_item(db: AsyncSession, user: User, project_id: str, item: WorkItem | None
                              ) -> WorkItem | None:
    """``item`` when it is the chat Workspace's and ``user`` may access it (``secure_work.access``), else ``None``:
    an item of another Workspace is used exactly like a missing one."""
    from ..secure_work.access import work_item_in_scope, work_scope_project_ids

    if item is None or not project_id or item.project_id != project_id:
        return None
    return item if work_item_in_scope(await work_scope_project_ids(db, user), item) else None


async def read_jira_issue(db: AsyncSession, *, session: AgentSession, key: str) -> dict[str, Any] | None:
    """``{"key", "title", "description", "issue_type"}`` of the Jira issue ``key``, or ``None`` when it cannot be read.

    A read failure (no Jira connection, a key that is no Jira issue such as ``UTF-8``) leaves the card as it was."""
    from ...tools import registry
    from ..workflow_runs.platform.dispatch import read_outcome

    if not session.project_id:
        return None
    try:
        context = await _chat_context(db, session, session.user_id)
        outcome = read_outcome(unfenced_result(
            await registry.execute_tool_with_plugins(READ_TOOL, {"ticket_id": key}, context)))
    except Exception:  # noqa: BLE001 - an unreadable issue only means the card cannot bind it
        logger.info("workflow_start.jira_read_failed", extra={"session_id": session.id}, exc_info=True)
        return None
    result = outcome.result if outcome.ok else {}
    title = _text(result.get("summary"))
    if not title:
        return None
    return {"key": _text(result.get("ticket_id")) or key, "title": title,
            "description": _text(result.get("description")), "issue_type": _text(result.get("issue_type"))}


__all__ = ["chat_workspace_item", "create_jira_issue", "jira_scope", "jira_work_item", "read_jira_issue",
           "workspace_jira_project", "writes_jira"]
