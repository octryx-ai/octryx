"""Test helpers: a repository record with its coding setup, as Settings → Workspace →
Repositories saves it, and its runtime projection (the ``work_repository_profiles`` row Coding reads).

The payload keys go to the record (name, provider, URL, branch) and its coding setup; the projection is returned serialized.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import core as db_core
from app.models import CodeRepository, User, WorkRepositoryProfile
from app.services.secure_work.repositories.record import save_setup


async def _admin(session) -> User:
    return (await session.execute(select(User).where(User.username == "admin"))).scalar_one()


async def create_repository_record(payload: dict[str, Any]) -> dict[str, Any]:
    """A record (or the given ``code_repository_id``'s) with ``payload`` as its coding setup; the projection."""
    async with db_core.async_session_factory() as session:
        repo = await session.get(CodeRepository, payload["code_repository_id"]) if payload.get("code_repository_id") else None
        if repo is None:
            repo = CodeRepository(project_id=payload.get("project_id"), name=str(payload.get("name") or "repository"),
                                  repo_root="", provider=str(payload.get("provider") or "bitbucket"),
                                  remote_url=payload.get("repository_url"), default_branch=payload.get("default_branch"),
                                  config_json={})
            session.add(repo)
            await session.flush()
        saved = await save_setup(session, user=await _admin(session), repo=repo, payload=payload)
        await session.commit()
        return saved["runtime_profile"]


async def update_repository_record(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Save ``payload`` as the coding setup of the record behind the projection ``profile_id``."""
    async with db_core.async_session_factory() as session:
        profile = await session.get(WorkRepositoryProfile, profile_id)
        repo = await session.get(CodeRepository, profile.code_repository_id)
        saved = await save_setup(session, user=await _admin(session), repo=repo, payload=payload)
        await session.commit()
        return saved["runtime_profile"]


__all__ = ["create_repository_record", "update_repository_record"]
