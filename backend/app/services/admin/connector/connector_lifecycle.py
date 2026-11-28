"""Pause, resume and guarded removal of a platform connector."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import BuiltInToolConfig, Project
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from ....models.runtime.named_connection import ConnectorNamedConnection
from ...tool_config import TOOL_CONFIG_PRESETS
from ..governance.admin_config_audit_service import record_admin_config_audit

STATE_CONNECTOR_IN_USE = "connector_in_use"
STATE_CONFIRMATION_MISMATCH = "connector_confirmation_mismatch"


def _require_known(tool_name: str) -> dict[str, Any]:
    preset = TOOL_CONFIG_PRESETS.get(tool_name)
    if preset is None:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return preset


async def connector_usage(db: AsyncSession, tool_name: str) -> dict[str, Any]:
    _require_known(tool_name)
    workspaces = (
        await db.execute(
            select(Project.name)
            .join(BuiltInToolConfig, BuiltInToolConfig.project_id == Project.id)
            .where(BuiltInToolConfig.tool_name == tool_name, BuiltInToolConfig.is_active.is_(True))
            .order_by(Project.name)
        )
    ).scalars().all()
    named = (
        await db.execute(
            select(ConnectorNamedConnection.name)
            .where(ConnectorNamedConnection.tool_name == tool_name)
            .order_by(ConnectorNamedConnection.name)
        )
    ).scalars().all()
    knowledge = int(
        (
            await db.execute(
                select(func.count()).select_from(KnowledgeSourceConnector).where(KnowledgeSourceConnector.kind == tool_name)
            )
        ).scalar_one()
    )
    return {
        "workspaces": list(workspaces),
        "named_connections": list(named),
        "knowledge_sources": knowledge,
        "references": len(workspaces) + len(named) + knowledge,
    }


async def set_connector_active(
    db: AsyncSession, *, tool_name: str, is_active: bool, actor_user_id: str | None
) -> dict[str, Any]:
    _require_known(tool_name)
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(BuiltInToolConfig.tool_name == tool_name, BuiltInToolConfig.project_id.is_(None))
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Connector not configured yet")
    before = bool(entry.is_active)
    entry.is_active = bool(is_active)
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.connector.resumed" if is_active else "admin.connector.paused",
        resource_type="connector_config",
        resource_id=tool_name,
        project_id=None,
        before={"is_active": before},
        after={"is_active": bool(is_active)},
        details={"connector_name": tool_name},
    )
    await db.commit()
    return {"tool_name": tool_name, "is_active": bool(entry.is_active)}


async def guarded_delete_connector(
    db: AsyncSession, *, tool_name: str, confirm_name: str, actor_user_id: str | None
) -> dict[str, Any]:
    from .admin_connector_service import delete_connector

    preset = _require_known(tool_name)
    expected = {tool_name.lower(), str(preset.get("label") or "").strip().lower()}
    if str(confirm_name or "").strip().lower() not in expected:
        raise HTTPException(status_code=422, detail={"code": STATE_CONFIRMATION_MISMATCH,
                                                     "message": "Type the connector's name to confirm."})
    usage = await connector_usage(db, tool_name)
    if usage["references"]:
        raise HTTPException(status_code=409, detail={"code": STATE_CONNECTOR_IN_USE,
                                                     "message": "Reassign or remove what uses it first.",
                                                     "usage": usage})
    return await delete_connector(db, tool_name=tool_name, actor_user_id=actor_user_id)


__all__ = [
    "STATE_CONFIRMATION_MISMATCH",
    "STATE_CONNECTOR_IN_USE",
    "connector_usage",
    "guarded_delete_connector",
    "set_connector_active",
]
