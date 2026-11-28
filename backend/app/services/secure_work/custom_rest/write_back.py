"""Write-back of a Work state to a Custom REST source, bound to one write operation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Role, UserRole, WorkItem, WorkItemSyncConfig, WorkItemWorkflowDefinition
from ...rest_connector.common import tool_name_for
from ...rest_connector.executor import run_operation
from ...rest_connector.runs import REFUSAL_CATEGORIES
from ..sync_policy import executes, load_item_intake
from .config import SOURCE_TYPE, intake_of_row
from .listing import IntakeCallContext, definition_by_key, operation_of

STATUS_PROPOSED = "proposed"
CODE_NOT_CONFIGURED = "write_back_not_configured"


def will_write(item: WorkItem, workflow: WorkItemWorkflowDefinition, sync_preview: Mapping[str, Any]) -> bool:
    return (str(item.source_type or "") == SOURCE_TYPE and executes(workflow.sync_policy_json, item)
            and bool(sync_preview.get("sync_back")) and bool(sync_preview.get("target_status")))


def write_effects(item: WorkItem, preview: Mapping[str, Any]) -> list[dict[str, Any]]:
    sync_preview = dict(preview.get("jira_sync_preview") or {})
    if not sync_preview.get("will_mutate_jira"):
        return []
    return [{"kind": "status", "value": sync_preview.get("target_status"), "target_status":
             sync_preview.get("target_status"), "transition": None}]


def render(template: Any, values: Mapping[str, str]) -> Any:
    if isinstance(template, str):
        rendered = template
        for name, value in values.items():
            rendered = rendered.replace("{" + name + "}", value)
        return rendered
    if isinstance(template, list):
        return [render(entry, values) for entry in template]
    if isinstance(template, Mapping):
        return {key: render(value, values) for key, value in template.items()}
    return template


async def _write_target(db: AsyncSession, item: WorkItem) -> tuple[Any, Any, dict[str, Any]]:
    row = await db.get(WorkItemSyncConfig, item.sync_config_id) if item.sync_config_id else None
    write_back = intake_of_row(row).get("write_back") if row is not None else None
    definition = await definition_by_key(db, str(item.source_instance or "")) if write_back else None
    operation = await operation_of(db, definition, write_back["operation"]) if definition is not None else None
    if operation is None:
        raise HTTPException(status_code=422, detail={
            "code": CODE_NOT_CONFIGURED,
            "message": "The workflow writes this state back, but the item's Custom REST intake names no enabled "
                       "write operation."})
    return definition, operation, write_back


async def _platform_roles(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(select(Role.name).join(UserRole, UserRole.role_id == Role.id)
                            .where(UserRole.user_id == user_id))
    return [name for (name,) in rows.all()]


async def execute_custom_rest_state_sync(db: AsyncSession, *, item: WorkItem, workflow: WorkItemWorkflowDefinition,
                                         preview: dict[str, Any]) -> dict[str, Any] | None:
    sync_preview = dict(preview.get("jira_sync_preview") or {})
    await load_item_intake(db, item)
    if not will_write(item, workflow, sync_preview):
        return None
    target = str(sync_preview["target_status"])
    applied_by = dict(preview.get("applied_by") or {})
    # Only a transition a person decided writes, as that person; any other is proposed and awaits a person
    if not applied_by.get("person") or not applied_by.get("user_id"):
        return {"executed": False, "status": STATUS_PROPOSED, "reason": "awaits_person", "target_status": target}
    definition, operation, write_back = await _write_target(db, item)
    values = {"source_key": str(item.source_key or ""), "source_id": str(item.source_id or item.source_key or ""),
              "target_status": target, "to_state": str(preview.get("to_state") or "")}
    params = dict(render(write_back.get("arguments") or {}, values))
    if write_back.get("body") is not None:
        params["body"] = render(write_back["body"], values)
    person = str(applied_by["user_id"])
    context = IntakeCallContext(user_id=person, project_id=str(item.project_id or ""), db=db,
                                roles=await _platform_roles(db, person))
    tool_name = tool_name_for(definition.key, operation.llm_name or operation.op_key)
    result = await run_operation(db, definition=definition, operation=operation, tool_name=tool_name, params=params,
                                 context=context)
    if "error" in result:
        category = str(result.get("code") or "request_failed")
        raise HTTPException(status_code=409 if category in REFUSAL_CATEGORIES else 502, detail={
            "code": f"custom_rest_{category}", "message": str(result["error"])})
    return {"executed": True, "operation": operation.op_key, "resulting_status": target,
            "run": result.get("run")}


__all__ = ["STATUS_PROPOSED", "execute_custom_rest_state_sync", "render", "will_write", "write_effects"]
