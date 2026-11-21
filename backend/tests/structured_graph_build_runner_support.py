"""Shared helpers for the test_structured_graph_build_runner_* modules."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.project.knowledge_structured import KnowledgeStructuredBuild
from app.services.knowledge.structured.build_runner import StructuredBuildRunner
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.structured_graph_support import CONSOLE_MANUAL, SERVER_MANUAL, seed_parsed_revision


def _factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _workspace(db) -> str:
    project_id = await seed_workspace(db)
    await seed_parsed_revision(db, project_id, source_key="server-manual", title="Server Manual", spans=SERVER_MANUAL)
    await seed_parsed_revision(db, project_id, source_key="console-guide", title="Console Guide",
                               spans=CONSOLE_MANUAL)
    return project_id


def _runner(db, **kwargs) -> StructuredBuildRunner:
    runtime, _, _ = build_runtime()
    return StructuredBuildRunner(_factory(db), runtime_provider=lambda: runtime, **kwargs)


async def _reload(db, build) -> KnowledgeStructuredBuild:
    return await db.get(KnowledgeStructuredBuild, build.id, populate_existing=True)
