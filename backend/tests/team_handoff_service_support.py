"""Shared helpers for the test_team_handoff_service_* modules."""

import pytest

from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse


@pytest.fixture(autouse=True)
async def own_tables(db):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])
