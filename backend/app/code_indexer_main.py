from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.services.error_facts import error_text

from .db import async_session_factory
from .models import CodeRepository
from .services.code_intelligence.indexing import run_code_index

log = logging.getLogger("octryx.code_indexer")


def _auto_index_interval_minutes(repo: CodeRepository) -> int:
    config = repo.config_json if isinstance(repo.config_json, dict) else {}
    try:
        value = int(config.get("auto_index_interval_minutes") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _is_due(repo: CodeRepository, now: datetime) -> bool:
    interval = _auto_index_interval_minutes(repo)
    if interval <= 0:
        return False
    if repo.last_indexed_at is None:
        return True
    last = repo.last_indexed_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return last + timedelta(minutes=interval) <= now


async def _run_once() -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        result = await db.execute(select(CodeRepository).where(CodeRepository.is_active.is_(True)))
        repositories = result.scalars().all()
        for repo in repositories:
            if not _is_due(repo, now):
                continue
            try:
                log.info("reindexing repository %s (%s)", repo.name, repo.id)
                await run_code_index(db, repository_id=repo.id, force=True, trigger="scheduler")
            except Exception as exc:
                log.warning("code index run failed for %s: %s", repo.id, error_text("code_index_run_failed", exc))


async def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    poll_seconds = max(5, int(os.environ.get("CODE_INDEXER_POLL_SECONDS", "60")))
    log.info("code indexer started with poll interval %ss", poll_seconds)
    while True:
        try:
            await _run_once()
        except Exception as exc:
            log.exception("code indexer loop failed: %s", exc)
        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
