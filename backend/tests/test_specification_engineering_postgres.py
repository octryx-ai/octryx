"""Real PostgreSQL: a spec-origin decision holds the origin's and the owner's authority until it commits,
so a concurrent membership revocation waits. Needs ``OCTRYX_TEST_POSTGRES_URL``."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import User, UserProject, WorkflowRun
from app.services.workflow_runs.decider import require_node_decider
from app.services.workflow_runs.records import WorkflowRunError
from tests.alembic_model_parity_support import migrated_database, requires_postgres
from tests.knowledge_retention_postgres_support import UNGRANTED_ROW_WAIT, until
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.specification_engineering_support import engineering_child_case, enter_node

pytestmark = pytest.mark.usefixtures("scripted_pool")


async def _scenario(url: str, revoked: str) -> None:
    from app.bootstrap import seed_database

    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as seed:
            await seed_database(seed)
            await seed.commit()
            # The engineer runs the building child on a terminal: the server refuses it.
            case = await engineering_child_case(seed, runtime_target={"kind": "terminal"})
            await enter_node(seed, case.child, "accept_functional")
            child_id, pm_id, project_id = case.child.id, case.pm.id, case.child.project_id
            target_id = pm_id if revoked == "pm" else case.engineer.id
        async with factory() as final, factory() as revoke, factory() as observer:
            run = await final.get(WorkflowRun, child_id)
            pm = await final.get(User, pm_id)
            resolution = await require_node_decider(final, run, pm)
            assert resolution.policy == "spec_origin" and resolution.allows(pm_id)

            async def revoke_membership() -> None:
                await revoke.execute(delete(UserProject).where(UserProject.user_id == target_id,
                                                               UserProject.project_id == project_id))
                await revoke.commit()

            pending = asyncio.create_task(revoke_membership())
            await until(observer, UNGRANTED_ROW_WAIT, 1)
            assert not pending.done()  # the decision transaction still holds the authority rows
            await final.commit()
            await asyncio.wait_for(pending, timeout=10)
        async with factory() as again:
            run = await again.get(WorkflowRun, child_id)
            with pytest.raises(WorkflowRunError) as refused:
                await require_node_decider(again, run, await again.get(User, pm_id))
            assert refused.value.code in {"decider_unresolved", "not_handoff_recipient", "stale_owner"}
            await again.rollback()
    finally:
        await engine.dispose()


@requires_postgres
@pytest.mark.parametrize("revoked", ["pm", "engineer"])
def test_spec_origin_decision_holds_origin_and_owner_membership_until_commit(tmp_path: Path, revoked: str) -> None:
    with migrated_database("postgresql", tmp_path) as database:
        asyncio.run(_scenario(database.url, revoked))
