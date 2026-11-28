"""Checks every 5 min with backoff, a real database health check, test button from the registry."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, ConnectorHealth, DatabaseConnector
from app.services.connector_health import refresh_all_connector_health
from app.services.connector_health.check_schedule import is_check_due, next_check_delay_seconds
from app.services.connector_test_service import CONNECTOR_TESTS
from app.services.database_tool import health as database_health
from app.services.database_tool_service import list_database_connectors
from app.time_utils import utc_now
from app.web._helpers.panel_serializers import _serialize_connector


def test_checks_run_every_five_minutes_and_back_off_while_failing():
    assert [next_check_delay_seconds(n) for n in range(6)] == [300, 600, 1200, 2400, 3600, 3600]
    now = utc_now()
    assert is_check_due(None, 0, now)
    assert not is_check_due(now - timedelta(minutes=4), 0, now)
    assert is_check_due(now - timedelta(minutes=5), 0, now)
    assert not is_check_due(now - timedelta(minutes=9), 1, now)


@pytest.mark.asyncio
async def test_the_worker_checks_a_connection_only_when_it_is_due(db):
    db.add(BuiltInToolConfig(id=str(uuid.uuid4()), tool_name="jira", project_id=None,
                             config={"jira_url": "https://jira.invalid"}, is_active=True))
    await db.commit()
    calls: list[str] = []

    async def failing(name, _config):
        calls.append(name)
        return {"ok": False, "summary": "Sign-in rejected"}

    await refresh_all_connector_health(db, run_connection_test=failing)
    await refresh_all_connector_health(db, run_connection_test=failing)
    assert calls == ["jira"], "a second tick within the backoff window must not check again"

    row = (await db.execute(select(ConnectorHealth).where(ConnectorHealth.connector_name == "jira"))).scalar_one()
    row.last_checked = utc_now() - timedelta(minutes=11)
    await db.commit()
    await refresh_all_connector_health(db, run_connection_test=failing)
    assert calls == ["jira", "jira"]


@pytest.mark.asyncio
async def test_a_database_card_shows_a_real_check_instead_of_connected(db, monkeypatch):
    connector = DatabaseConnector(id=str(uuid.uuid4()), name="reporting", db_type="postgresql",
                                  connection_config={"host": "db.invalid"}, is_active=True)
    db.add(connector)
    await db.commit()
    listed = next(row for row in await list_database_connectors(db) if row["id"] == connector.id)
    assert listed["health"] is None, "never checked is not 'Connected'"

    async def unreachable(_db, connector_id):
        return {"ok": False, "summary": "Host not reachable"}

    monkeypatch.setattr("app.services.database_tool_service.test_database_connector", unreachable)
    await database_health.refresh_due_database_health(db, now=utc_now())
    await db.commit()

    listed = next(row for row in await list_database_connectors(db) if row["id"] == connector.id)
    assert listed["health"]["status"] == "error"
    assert listed["health"]["error"] == "Host not reachable"


def test_the_test_button_follows_the_registered_connection_tests():
    serialized = _serialize_connector("servicenow", None, None)
    assert serialized["supports_test"] is ("servicenow" in CONNECTOR_TESTS)
    assert "servicenow" in CONNECTOR_TESTS
