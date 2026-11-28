"""Starting a run (``records.start_run``): its scope, target, repository and responsible person."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from .records import WorkflowRunError


@dataclass
class StartPlan:
    item: WorkItem | None
    scope: str | None
    target: Any
    phased: Any
    repository: str | None
    context: dict[str, Any] | None
    responsible: tuple[str | None, str | None]


async def start_work_item(db: AsyncSession, work_item_id: str | None) -> WorkItem | None:
    if not work_item_id:
        return None
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise WorkflowRunError("unknown_work_item", "The Work item does not exist.", 404)
    return item


async def _start_target(db: AsyncSession, *, user: User, scope: str, raw: Any, repository: str | None,
                        session: Any) -> dict[str, Any] | None:
    from ..devices.chat_turn import device_thread_target
    from .runtime_target.target import validate_target

    # A run named no runtime from a thread that runs on a device or runner: it runs where its thread runs.
    if raw is None and session is not None and device_thread_target(session) is not None:
        return None
    return await validate_target(db, user=user, project_id=scope, raw=raw, repository=repository)


async def plan_start(db: AsyncSession, *, user: User, workflow_key: str, project_id: str | None,
                     work_item_id: str | None, repository: str | None, session: Session | None,
                     parent: WorkflowRun | None, context: dict[str, Any] | None, runtime_target: Any,
                     automatic: bool, responsible: tuple[str | None, str | None] | None) -> StartPlan:
    from .access import require_start_scope
    from .engine import published_phased_flow
    from .runtime_target.server_build import refuse_server_build
    from .runtime_target.target import apply_to_thread, with_target

    item = await start_work_item(db, work_item_id)
    scope = project_id or (item.project_id if item is not None else None)
    # Every start path (API, chat, Work item, Action, octryx, a sub-workflow): a run lives in a Workspace, refused
    # first and typed (``access.require_start_workspace``).
    await require_start_scope(db, user, project_id=scope, item=item)
    if not repository and isinstance(runtime_target, (dict, str)) and (
            runtime_target == "auto" or (isinstance(runtime_target, dict) and runtime_target.get("kind") == "auto")):
        from .definition_of_ready import default_repository

        repository = await default_repository(db, item.id if item is not None else None, scope)
    target = await _start_target(db, user=user, scope=scope, raw=runtime_target, repository=repository,
                                 session=session)
    phased = await published_phased_flow(db, workflow_key, scope)
    if phased is None:
        from ..run_admission.archived_workflows import is_archived_workflow_key
        from ..run_admission.denials import WORKFLOW_ARCHIVED

        if await is_archived_workflow_key(db, workflow_key, project_id=scope):  # typed, never 404
            raise WorkflowRunError(WORKFLOW_ARCHIVED, f"Workflow '{workflow_key}' is archived or switched off.", 409)
        raise WorkflowRunError("unknown_workflow", f"No published workflow '{workflow_key}'.", 404)
    # A build/test workflow never starts on the server, thread untouched.
    refuse_server_build(target, workflow_key=workflow_key, where="start", thread=session, actor_id=user.id,
                        definition=dict(phased[1].definition_json or {}))
    from .runtime_target.folder_lock import refuse_busy_folder

    await refuse_busy_folder(db, target, parent_run_id=parent.id if parent is not None else None)
    context = with_target(context, target, actor_id=user.id) if target is not None else context
    apply_to_thread(session, target)
    if parent is None:
        from .succession import require_no_active_run

        await require_no_active_run(db, item, workflow_key)
    if not repository:
        from .definition_of_ready import default_repository

        repository = await default_repository(db, item.id if item is not None else None, scope)
    from .responsible import initial_responsible

    if responsible is None:
        responsible = await initial_responsible(db, user=user, item=item, project_id=scope, parent=parent,
                                                automatic=automatic)
    # A person's start of an epic's story builds on the chain (``epic_chain``).
    if parent is None:
        from .epic_chain import story_start_context

        context = await story_start_context(db, item, phased[0].key, context)
    return StartPlan(item=item, scope=scope, target=target, phased=phased, repository=repository, context=context,
                     responsible=responsible)


async def startable_workflows_for(db: AsyncSession, *, project_id: str | None) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    from ...models import FlowDefinition
    from ...models.runtime.flow_definition import FlowDefinitionVersion
    from .graph import is_phased_definition

    listed: dict[str, dict[str, Any]] = {}
    flows = await db.execute(
        select(FlowDefinition, FlowDefinitionVersion)
        .join(FlowDefinitionVersion, FlowDefinitionVersion.id == FlowDefinition.current_version_id)
        .where(FlowDefinition.status == "published", FlowDefinition.is_active.is_(True),
               FlowDefinitionVersion.status == "published",
               or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id))
    )
    from .start_trigger import STARTED_BY_PULL_REQUEST, started_by

    for flow, version in flows.all():
        definition = dict(version.definition_json or {})
        if is_phased_definition(definition) and started_by(definition) != STARTED_BY_PULL_REQUEST:
            # a workflow a pull request starts (its Start box says so) is never started by a person from this list
            listed[flow.key] = {"key": flow.key, "title": flow.name, "kind": "phased"}
    return sorted(listed.values(), key=lambda item: item["title"].lower())
