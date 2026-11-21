"""Row importers for users, skills, tasks and agent definitions: each row succeeds or fails on its own."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth import hash_password
from app.services.error_facts import error_text
from app.services.export_package import (
    _upsert_agent_from_package,
    _upsert_skill_from_package,
    _upsert_task_from_package,
)

from ...models import User


async def _import_user_rows(
    db: AsyncSession,
    *,
    rows: list[dict[str, Any]],
    overwrite_existing: bool,
) -> tuple[int, int, list[str]]:
    success = 0
    failed = 0
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            username = str(row.get("username") or "").strip()
            email = str(row.get("email") or "").strip()
            if not username or not email:
                raise ValueError("username and email are required")
            existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if existing and not overwrite_existing:
                raise ValueError(f"user '{username}' already exists")
            user = existing or User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                password_hash=hash_password("ImportedUser!123"),
                auth_source="local",
            )
            user.display_name = str(row.get("display_name") or username)
            user.is_active = bool(row.get("is_active", True))
            db.add(user)
            success += 1
        except Exception as exc:
            failed += 1
            errors.append(f"row {idx}: {error_text('data_import_row_failed', exc)}")
    return success, failed, errors


async def _import_skill_rows(
    db: AsyncSession,
    *,
    current_user: User,
    rows: list[dict[str, Any]],
    overwrite_existing: bool,
) -> tuple[int, int, list[str]]:
    success = 0
    failed = 0
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            entity = row.get("entity") if isinstance(row, dict) and isinstance(row.get("entity"), dict) else row
            await _upsert_skill_from_package(
                db,
                current_user=current_user,
                entity=entity,
                overwrite_existing=overwrite_existing,
                name_override=None,
            )
            success += 1
        except Exception as exc:
            failed += 1
            errors.append(f"row {idx}: {error_text('data_import_row_failed', exc)}")
    return success, failed, errors


async def _import_task_rows(
    db: AsyncSession,
    *,
    current_user: User,
    rows: list[dict[str, Any]],
    target_project_id: str,
    overwrite_existing: bool,
) -> tuple[int, int, list[str]]:
    success = 0
    failed = 0
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            entity = row.get("entity") if isinstance(row, dict) and isinstance(row.get("entity"), dict) else row
            await _upsert_task_from_package(
                db,
                current_user=current_user,
                entity=entity,
                overwrite_existing=overwrite_existing,
                name_override=None,
                target_project_id=target_project_id,
            )
            success += 1
        except Exception as exc:
            failed += 1
            errors.append(f"row {idx}: {error_text('data_import_row_failed', exc)}")
    return success, failed, errors


async def _import_agent_rows(
    db: AsyncSession,
    *,
    current_user: User,
    rows: list[dict[str, Any]],
    target_project_id: str,
    overwrite_existing: bool,
) -> tuple[int, int, list[str]]:
    # ``target_project_id`` is part of the row-importer protocol; agents are Global and ignore it.
    del target_project_id
    success = 0
    failed = 0
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        try:
            entity = row.get("entity") if isinstance(row, dict) and isinstance(row.get("entity"), dict) else row
            await _upsert_agent_from_package(
                db,
                current_user=current_user,
                entity=entity,
                overwrite_existing=overwrite_existing,
                name_override=None,
            )
            success += 1
        except HTTPException as exc:
            failed += 1
            # A typed denial is named, not hidden behind the error type.
            code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
            errors.append(f"row {idx}: {code or error_text('data_import_row_failed', exc)}")
        except Exception as exc:
            failed += 1
            errors.append(f"row {idx}: {error_text('data_import_row_failed', exc)}")
    return success, failed, errors
