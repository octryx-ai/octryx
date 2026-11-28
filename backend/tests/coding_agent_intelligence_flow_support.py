"""Shared helpers for the test_coding_agent_intelligence_flow_* modules."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.bootstrap import seed_database
from app.services.budget.unpriced_guard import POLICY_WARN, set_unpriced_model_policy


async def _seed(db: AsyncSession) -> None:
    await seed_database(db)
    await set_unpriced_model_policy(db, POLICY_WARN)


def _create_test_engine(tmp_path: Path, name: str):
    return create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / name}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


def _write_fixture(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "app.py").write_text(
        "def helper() -> str:\n    return 'hello world'\n\ndef use_helper() -> str:\n    return helper()\n",
        encoding="utf-8",
    )


def _has_verified_coding_completion(events: list[tuple[str, str]]) -> bool:
    return any(
        role == "assistant" and content.startswith("Implemented the requested coding change")
        for role, content in events
    )


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
