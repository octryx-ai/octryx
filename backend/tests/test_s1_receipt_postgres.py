"""Two concurrent calls to the real S1 consume service, on independent PostgreSQL sessions."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import DocumentationAudienceReceipt, WorkflowRun, WorkflowRunEvent
from app.services.workflow_runs.documentation import audience_receipt as receipts
from app.services.workflow_runs.documentation import receipt_record
from tests.alembic_model_parity_support import migrated_database
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user
from tests.knowledge_retention_postgres_support import (
    UNGRANTED_ROW_WAIT,
    requires_postgres,
    until,
)
from tests.s1_receipt_flow_support import bind_publication

pytestmark = pytest.mark.asyncio


@pytest.fixture
def receipt_database(tmp_path):
    # Independent migrated scratch DB: cleanup cannot affect a shared ledger or Acceptance.
    with migrated_database("postgresql", tmp_path) as database:
        yield database


@requires_postgres
async def test_two_consumers_lock_the_run_and_only_one_consumes_the_receipt(receipt_database):
    engine = create_async_engine(receipt_database.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    runtime, _s3, evidence_index = build_runtime()
    bound = None
    try:
        async with factory() as seed:
            bound = await bind_publication(seed, runtime, evidence_index)
            receipt = await receipts.issue_audience_challenge(seed, bound.run)
            await seed.commit()
            await receipt_record.record_audience_receipt(seed, current_user=await fetch_user(seed, bound.principal),
                workspace_id=bound.workspace, proof_request={"challenge_id": receipt.challenge_id}, runtime=runtime)
            await seed.commit()
            receipt_id, run_id = receipt.id, bound.run.id
        async with factory() as first, factory() as second, factory() as observer:
            run_one = await first.get(WorkflowRun, run_id)
            run_two = await second.get(WorkflowRun, run_id)
            winner = await receipts.consume_audience_receipt(first, run_one)
            assert winner.ok
            rival = asyncio.create_task(receipts.consume_audience_receipt(second, run_two))
            await until(observer, UNGRANTED_ROW_WAIT, 1)
            assert not rival.done()
            await first.commit()
            loser = await asyncio.wait_for(rival, timeout=10)
            assert not loser.ok and loser.result["code"] == "replayed"
            await second.commit()
            await observer.rollback()
            row = await observer.get(DocumentationAudienceReceipt, receipt_id)
            assert row.state == "consumed" and row.recorded_by == bound.principal
            count = (await observer.execute(select(func.count()).select_from(WorkflowRunEvent).where(
                WorkflowRunEvent.run_id == run_id, WorkflowRunEvent.kind == receipts.EVENT_CONSUMED))).scalar_one()
            assert count == 1
    finally:
        await engine.dispose()
