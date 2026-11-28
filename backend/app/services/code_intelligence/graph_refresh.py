"""Keep a repository's code graph current: mirror it, then index it."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from ..data_access import background_viewer, run_as
from .mirror import MirrorError, ensure_mirror, mirror_root

logger = logging.getLogger(__name__)
_BACKGROUND: set[asyncio.Task] = set()


async def refresh(db: AsyncSession, repo: CodeRepository, *, trigger: str) -> dict[str, Any]:
    from .indexing import run_code_index

    outcome: dict[str, Any] = {"repository_id": repo.id, "trigger": trigger}
    if mirror_root() is not None and repo.remote_url:
        try:
            outcome["mirror"] = await ensure_mirror(db, repo)
            await db.commit()
        except MirrorError as error:
            outcome["mirror_error"] = error.reason
            logger.warning("code_graph.mirror_failed", extra={"repository_id": repo.id, "reason": error.reason})
        except Exception as error:  # noqa: BLE001 - one repository's mirror never stops the others
            await db.rollback()
            outcome["mirror_error"] = f"unexpected: {type(error).__name__}"
            logger.exception("code_graph.mirror_failed", extra={"repository_id": repo.id})
    if repo.graph_backend == "disabled":
        outcome["index"] = "graph disabled for this repository"
        return outcome
    try:
        outcome["index"] = await run_code_index(db, repository_id=repo.id, force=trigger == "backfill",
                                                trigger=trigger)
    except Exception as error:  # noqa: BLE001 - one repository's failure never stops the others
        outcome["index_error"] = str(getattr(error, "detail", "") or error)[:300]
    return outcome


def _slug(value: str) -> str:
    text = re.sub(r"\.git$", "", str(value or "").strip().lower().rstrip("/"))
    text = re.sub(r"^.*?://[^/]+/", "", text)
    text = text.removeprefix("scm/")
    parts = [part for part in text.split("/") if part]
    return "/".join(parts[-2:])


async def repositories_for(db: AsyncSession, repository: str, project_id: str | None) -> list[CodeRepository]:
    wanted = _slug(repository)
    if not wanted:
        return []
    query = select(CodeRepository).where(CodeRepository.is_active.is_(True), CodeRepository.remote_url.is_not(None))
    if project_id is not None:
        query = query.where(CodeRepository.project_id == project_id)
    return [repo for repo in (await db.execute(query)).scalars().all() if _slug(repo.remote_url) == wanted]


async def _refresh_isolated(repository_ids: list[str], trigger: str) -> None:
    from ...db import core as db_core

    async with db_core.async_session_factory() as db:
        for repository_id in repository_ids:
            repo = await db.get(CodeRepository, repository_id)
            if repo is None:
                continue
            try:
                await refresh(db, repo, trigger=trigger)
            except Exception:  # noqa: BLE001 - logged; the next merge or a backfill tries again
                logger.exception("code_graph.refresh_failed", extra={"repository_id": repository_id})
                await db.rollback()


async def on_pr_merged(db: AsyncSession, repository: str, project_id: str | None) -> list[str]:
    ids = [repo.id for repo in await repositories_for(db, repository, project_id)]
    if ids:
        refresh = _refresh_isolated(ids, "pr_merged")
        task = asyncio.get_running_loop().create_task(run_as(background_viewer(), refresh))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
    return ids


async def backfill(db: AsyncSession, *, project_id: str | None = None) -> list[dict[str, Any]]:
    query = select(CodeRepository).where(CodeRepository.is_active.is_(True), CodeRepository.remote_url.is_not(None))
    if project_id is not None:
        query = query.where(CodeRepository.project_id == project_id)
    results = []
    for repo in (await db.execute(query)).scalars().all():
        results.append(await refresh(db, repo, trigger="backfill"))
    return results


__all__ = ["backfill", "on_pr_merged", "refresh", "repositories_for"]
