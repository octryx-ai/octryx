"""Repository CRUD helpers for code intelligence."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import CodeRepository
from ...time_utils import utc_now
from .graph_admin import get_code_graph_admin_status_for_repository
from .storage_capabilities import detect_code_intelligence_capabilities
from .storage_repository import _serialize_repository
from .storage_runtime import _normalize_repository_payload, _repository_storage_dir


async def list_code_repositories(db: AsyncSession, *, project_id: str | None = None) -> list[dict[str, Any]]:
    query = (
        select(CodeRepository)
        .options(selectinload(CodeRepository.index_runs))
        .order_by(CodeRepository.updated_at.desc())
    )
    if project_id:
        query = query.where(CodeRepository.project_id == project_id)
    result = await db.execute(query)
    items = []
    for repo in result.scalars().all():
        serialized = _serialize_repository(repo)
        serialized["code_graph_status"] = await get_code_graph_admin_status_for_repository(db, repo=repo)
        items.append(serialized)
    return items


async def get_code_repository(db: AsyncSession, repository_id: str) -> CodeRepository:
    result = await db.execute(
        select(CodeRepository)
        .options(selectinload(CodeRepository.index_runs))
        .where(CodeRepository.id == repository_id)
    )
    repo = result.scalar_one_or_none()
    if repo is None:
        raise HTTPException(status_code=404, detail="Code repository not found")
    return repo


async def create_code_repository(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_repository_payload(payload)
    capabilities = detect_code_intelligence_capabilities()
    repo = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=str(payload.get("project_id") or "").strip() or None,
        capabilities_json=capabilities,
        latest_index_summary={},
        last_index_status="not_indexed",
        **normalized,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return _serialize_repository(repo)


# ``config_json`` keys that their own APIs own (``api/routes/pr_review_bot.py``): the repository form never sends
# them, so its update keeps them. Otherwise an admin who saves the repository
# in the panel would switch the PR review bot off without a word.
OWNED_CONFIG_KEYS = ("pr_review_bot", "pr_review_bot_state")


async def update_code_repository(db: AsyncSession, repository_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    repo = await get_code_repository(db, repository_id)
    owned = {key: value for key, value in dict(repo.config_json or {}).items() if key in OWNED_CONFIG_KEYS}
    normalized = _normalize_repository_payload({**_current_fields(repo), **payload})
    for field, value in normalized.items():
        if field in payload:
            setattr(repo, field, value)
    if "config_json" in payload:
        kept = {key: value for key, value in owned.items() if key not in normalized["config_json"]}
        repo.config_json = {**normalized["config_json"], **kept}
    repo.capabilities_json = detect_code_intelligence_capabilities()
    repo.updated_at = utc_now()
    await db.commit()
    await db.refresh(repo)
    return _serialize_repository(repo)


def _current_fields(repo: CodeRepository) -> dict[str, Any]:
    return {"name": repo.name, "description": repo.description, "repo_root": repo.repo_root,
            "provider": repo.provider, "remote_url": repo.remote_url, "default_branch": repo.default_branch,
            "index_backend": repo.index_backend, "semantic_backend": repo.semantic_backend,
            "structure_backend": repo.structure_backend, "graph_backend": repo.graph_backend,
            "config_json": dict(repo.config_json or {}), "is_active": repo.is_active}


async def delete_code_repository(db: AsyncSession, repository_id: str) -> None:
    repo = await get_code_repository(db, repository_id)
    await db.delete(repo)
    await db.commit()
    storage = _repository_storage_dir(repository_id)
    if storage.exists():
        shutil.rmtree(storage, ignore_errors=True)
