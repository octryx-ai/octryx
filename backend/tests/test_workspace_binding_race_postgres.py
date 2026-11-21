"""Parallel first loads of a Workspace on a real, migrated PostgreSQL: all succeed, one binding per runtime.

The first page of a fresh install (the setup guide) asks for the Workspace's onboarding status twice at once. Each
request loads the Workspace's execution view, which exposes every active runtime target as a Workspace binding
(``workspace_composition.sync_workspace_runtime_catalog_bindings``). Before the fix both requests read "no binding
yet" and both inserted it: the second hit ``uq_workspace_capability_bindings_workspace_key`` and the guide showed
"The setup status could not be loaded".

Skipped unless ``OCTRYX_TEST_POSTGRES_URL`` names a disposable server; the scratch database is created and
dropped by the test.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    CapabilityType,
    ControlPlaneRuntimeTarget,
    LLMModel,
    LLMProvider,
    Project,
    WorkspaceCapabilityBinding,
)
from app.services.model_selection.platform_order import active_config
from app.services.workspace_composition.execution_view import get_workspace_execution_view
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres

PARALLEL = 12
TARGETS = ("model-a", "model-b", "model-c")


async def _round(url: str) -> tuple[list[object], int, int]:
    engine = create_async_engine(url, pool_size=PARALLEL, max_overflow=0)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            provider = LLMProvider(name=f"p-{uuid.uuid4().hex[:6]}", driver="bedrock_api", display_name="P",
                                   is_active=True)
            db.add(provider)
            await db.flush()
            config = await active_config(db, create=True)
            db.add_all([LLMModel(provider_id=provider.id, model_id=name, display_name=name, is_active=True,
                                 cleared_up_to="internal") for name in TARGETS])
            await db.flush()
            db.add_all([ControlPlaneRuntimeTarget(config_id=config.id, provider_id=provider.id, model_id=name,
                                                  priority=index, is_active=True)
                        for index, name in enumerate(TARGETS, start=1)])
            workspace = Project(id=str(uuid.uuid4()), name="Fresh Workspace", is_active=True)
            db.add(workspace)
            await db.commit()

        async def first_load(_n: int) -> object:
            try:
                async with maker() as db:
                    view = await get_workspace_execution_view(db, workspace_id=workspace.id)
                    await db.commit()
                    return view["workspace_id"] if view else None
            except Exception as error:  # noqa: BLE001 - the failure is the finding
                return repr(error)[:300]

        results = await asyncio.gather(*(first_load(n) for n in range(PARALLEL)))
        async with maker() as db:
            bindings = (await db.execute(select(func.count()).select_from(WorkspaceCapabilityBinding).where(
                WorkspaceCapabilityBinding.workspace_id == workspace.id,
                WorkspaceCapabilityBinding.capability_kind == "runtime"))).scalar_one()
            types = (await db.execute(select(func.count()).select_from(CapabilityType).where(
                CapabilityType.kind == "runtime"))).scalar_one()
        return results, bindings, types
    finally:
        await engine.dispose()


def test_parallel_first_loads_of_a_workspace_all_succeed(tmp_path: Path):
    with migrated_database("postgresql", tmp_path) as database:
        results, bindings, types = asyncio.run(_round(database.url))
    assert len(set(results)) == 1 and isinstance(results[0], str) and len(results[0]) == 36, results
    assert bindings == len(TARGETS)
    assert types >= len(TARGETS)
