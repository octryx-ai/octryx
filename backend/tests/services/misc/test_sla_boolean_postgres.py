"""Actual SLA service behavior on private SQLite/PostgreSQL scratch DBs with Boolean columns."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import Project, SLABreach, SLADefinition, Task, TaskRun, User
from app.services.sla import service
from app.time_utils import utc_now
from tests.alembic_model_parity_support import DIALECTS, scratch_database


@pytest.fixture(params=DIALECTS)
def sla_database(request, tmp_path):
    with scratch_database(request.param, tmp_path) as database:
        database.run(lambda connection: Base.metadata.create_all(connection))
        yield database


def test_existing_task_runs_active_filter_resolution_and_boolean_writes(sla_database, monkeypatch):
    notified = AsyncMock()
    monkeypatch.setattr(service, "create_notification", notified)

    async def scenario():
        engine = create_async_engine(sla_database.url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        queries = []

        @event.listens_for(engine.sync_engine, "before_execute")
        def capture(_connection, clause, _multiparams, _params, _options):
            if getattr(clause, "is_select", False):
                queries.append(str(clause.compile(dialect=postgresql.dialect())))

        try:
            async with factory() as db:
                user = User(username="sla-fixture", email="sla-fixture@example.invalid", password_hash="fixture-only")
                project = Project(name="SLA isolated fixture")
                db.add_all([user, project])
                await db.flush()
                tasks = [Task(dispatch_binding="task_definition", project_id=project.id, name=name, task_type="agent_run", agent_type="diagnosis",
                              owner_id=user.id, is_active=True) for name in ("warning", "overdue", "inactive")]
                db.add_all(tasks)
                await db.flush()
                now = utc_now()
                runs = [TaskRun(task_id=task.id, started_by=user.id, status="running",
                                started_at=now - timedelta(seconds=duration))
                        for task, duration in zip(tasks, (450, 1200, 1200), strict=True)]
                db.add_all(runs)
                await db.commit()
                defs = []
                for task, active in zip(tasks, (True, True, False), strict=True):
                    definition = await service.create_sla_definition(db, payload={
                        "name": task.name, "task_id": task.id, "max_duration_seconds": 600,
                        "alert_threshold": 0.5, "is_active": active})
                    assert definition["is_active"] is active
                    defs.append(definition)
                first = await service.process_sla_breaches(db)
                assert first["checked_runs"] == 3 and first["definitions_matched"] == 2
                assert first["breaches_created"] == 3 and first["breaches_resolved"] == 0
                assert notified.await_count == 3
                rows = (await db.execute(select(SLABreach))).scalars().all()
                assert all(row.is_resolved is False and row.notification_sent is True for row in rows)
                assert {row.task_id for row in rows} == {tasks[0].id, tasks[1].id}
                assert {row.breach_type for row in rows if row.task_id == tasks[1].id} == {
                    "warning_threshold", "duration_exceeded"}
                runs[0].status, runs[0].completed_at = "completed", now
                await db.commit()
                second = await service.process_sla_breaches(db)
                assert second["breaches_created"] == 0 and second["breaches_resolved"] == 1
                assert notified.await_count == 3
                all_rows = await service.list_sla_breaches(db)
                open_rows = await service.list_sla_breaches(db, unresolved_only=True)
                assert len(all_rows) == 3 and len(open_rows) == 2
                assert all(row["is_resolved"] is False for row in open_rows)
                assert sum(row["is_resolved"] is True for row in all_rows) == 1
                assert (await service.update_sla_definition(db, definition_id=defs[1]["id"],
                                                           payload={"is_active": False}))["is_active"] is False
                assert (await db.get(SLADefinition, defs[1]["id"])).is_active is False
                assert (await service.update_sla_definition(db, definition_id=defs[1]["id"],
                                                           payload={"is_active": True}))["is_active"] is True
            compiled = "\n".join(queries).lower()
            assert "sla_definitions.is_active is true" in compiled
            assert "sla_breaches.is_resolved is false" in compiled
            assert "sla_definitions.is_active = 1" not in compiled
            assert "sla_breaches.is_resolved = 0" not in compiled
        finally:
            await engine.dispose()

    asyncio.run(scenario())
