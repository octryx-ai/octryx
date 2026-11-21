"""Session-workspace and Office template update handlers for admin runtime settings."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...office.template import normalize_office_template_library
from ...session.workspace import save_session_workspace_settings
from ...session.workspace_storage import normalize_workspace_storage_backend, normalize_workspace_storage_prefix
from ...session.workspace_sync import save_workspace_sync_policy_settings
from ...system_config import (
    AGENT_OFFICE_TEMPLATE_LIBRARY_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
    set_system_config_value,
)

_SYNC_POLICY_FIELDS = (
    "session_workspace_sync_excluded_dirs",
    "session_workspace_sync_excluded_globs",
    "session_workspace_sync_max_file_size_bytes",
    "session_workspace_sync_max_file_count",
)


async def apply_session_workspace_settings(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "session_workspace_base_dir" in payload:
        await save_session_workspace_settings(db, base_dir=str(payload.get("session_workspace_base_dir") or "").strip())
    if "session_workspace_max_age_hours" in payload:
        await save_session_workspace_settings(
            db,
            max_age_hours=int(payload.get("session_workspace_max_age_hours") or 0),
        )
    await _apply_workspace_storage_settings(db, payload)
    if any(field in payload for field in _SYNC_POLICY_FIELDS):
        await _save_sync_policy(db, payload)


async def _apply_workspace_storage_settings(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "session_workspace_storage_backend" in payload:
        backend = normalize_workspace_storage_backend(payload.get("session_workspace_storage_backend"))
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
            value=backend if backend != "disabled" else None,
            description="Durable object-storage backend for per-session workspaces.",
        )
    if "session_workspace_storage_bucket" in payload:
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
            value=str(payload.get("session_workspace_storage_bucket") or "").strip() or None,
            description="Bucket name, or filesystem root for filesystem-backed session workspace storage.",
        )
    if "session_workspace_storage_prefix" in payload:
        try:
            prefix = normalize_workspace_storage_prefix(payload.get("session_workspace_storage_prefix"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await set_system_config_value(
            db,
            key=AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
            value=prefix or None,
            description="Relative object prefix for per-session workspace storage.",
        )


async def _save_sync_policy(db: AsyncSession, payload: dict[str, Any]) -> None:
    await save_workspace_sync_policy_settings(
        db,
        excluded_dirs=(
            str(payload.get("session_workspace_sync_excluded_dirs") or "")
            if "session_workspace_sync_excluded_dirs" in payload
            else None
        ),
        excluded_globs=(
            str(payload.get("session_workspace_sync_excluded_globs") or "")
            if "session_workspace_sync_excluded_globs" in payload
            else None
        ),
        max_file_size_bytes=(
            int(payload.get("session_workspace_sync_max_file_size_bytes") or 0)
            if "session_workspace_sync_max_file_size_bytes" in payload
            else None
        ),
        max_file_count=(
            int(payload.get("session_workspace_sync_max_file_count") or 0)
            if "session_workspace_sync_max_file_count" in payload
            else None
        ),
    )


async def apply_office_settings(db: AsyncSession, payload: dict[str, Any]) -> None:
    if "office_template_library" in payload:
        normalized = normalize_office_template_library(payload.get("office_template_library"))
        await set_system_config_value(
            db,
            key=AGENT_OFFICE_TEMPLATE_LIBRARY_KEY,
            value=json.dumps(normalized, ensure_ascii=False) if normalized else None,
            description="Configurable Office template library for document generation and merge flows.",
        )
