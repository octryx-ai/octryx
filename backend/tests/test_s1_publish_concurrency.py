"""One actual service sender across independent DB sessions, on Alembic-built scratch databases."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import DocumentationWriteIntent, User, WorkflowRun
from app.services.workflow_runs.documentation import publication_v2 as publication
from app.services.workflow_runs.records import WorkflowRunError, lock_run
from tests.s1_publication_models_support import database, migrated_template  # noqa: F401 - pytest fixtures
from tests.s1_publish_cloud_support import FakeCloudV2
from tests.s1_publish_run_support import publish, published_ready


def test_one_sender_service_durable_claim_and_independent_worker_refusal(database, monkeypatch):  # noqa: F811
    scratch = database
    async def scenario():
        engine = create_async_engine(scratch.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        fake = FakeCloudV2()
        try:
            async with sessions() as first:
                first.add(User(username="admin", email="admin@example.invalid", password_hash="fixture-only"))
                await first.commit()
                run, intent = await published_ready(first, fake)
                seen = []

                async def observe_claim(_intent):
                    async with sessions() as second:
                        persisted = await second.get(DocumentationWriteIntent, intent.id)
                        assert persisted.state == "send_started" and persisted.claimed_by == "first"
                        assert fake.writes == []  # the durable marker preceded transport
                        other = await second.get(WorkflowRun, run.id)
                        await lock_run(second, other)
                        with pytest.raises(WorkflowRunError) as error:
                            await publication.publish_documentation_v2(second, other, transport=fake.transport(),
                                                                       worker_id="second")
                        assert error.value.code == "action_in_flight"
                        seen.append(True)
                        await second.rollback()

                monkeypatch.setattr(publication, "_before_send", observe_claim)
                outcome = await publish(first, run, fake, worker="first")
                assert outcome.ok and seen == [True] and len(fake.writes) == 1
                again = await publish(first, run, fake, entry=2, worker="second")
                assert again.ok and len(fake.writes) == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())
