"""Shared helpers for the test_rest_connector_executor_* modules."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import RestApiCallRun, User
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import create_definition, update_operation
from app.tools.context import ToolContext
from tests.rest_connector_support import API, SECRET, recorded_api

LIST_TOOL = "rest__tickets__list_tickets"


OPERATIONS = [
    {"op_key": "list_tickets", "method": "GET", "path": "/tickets",
     "parameters": [{"name": "assignment_group", "in": "query"}, {"name": "state", "in": "query"}]},
    {"op_key": "get_ticket", "method": "GET", "path": "/tickets/{id}", "parameters": [{"name": "id", "in": "path"}]},
    {"op_key": "close_ticket", "method": "POST", "path": "/tickets/{id}/close",
     "parameters": [{"name": "id", "in": "path"}]},
]


SCOPED_GRANT = {"role": "agent", "scope": {"assignment_group": "G1"},
                "result_filter": {"field": "assignment_group", "value": "G1"}}


@pytest.fixture
def api(monkeypatch):
    return recorded_api(monkeypatch)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _setup(db, *, auth=None, secrets=None, grants=None, pagination=None, enable=("list_tickets",)):
    admin = await _admin(db)
    definition = await create_definition(db, {"key": "tickets", "name": "Tickets", "auth": auth or {"scheme": "bearer"},
                                               "operations": OPERATIONS}, actor_user_id=admin.id)
    await create_connection(db, definition["id"], {"base_url": API, **({"token": SECRET} if secrets is None else secrets)})
    operations = {operation["op_key"]: operation for operation in definition["operations"]}
    for op_key in enable:
        payload = {"enabled": True, "grants": [SCOPED_GRANT] if grants is None else grants}
        if pagination and op_key == "list_tickets":
            payload["pagination"] = pagination
        await update_operation(db, definition["id"], operations[op_key]["id"], payload)
    return definition, operations


def _context(db, user_id: str, roles=("agent",), run_capability=None) -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=list(roles), session_id=str(uuid.uuid4()),
                       project_config={}, db=db, run_capability=run_capability)


async def _runs(db) -> list[RestApiCallRun]:
    return list((await db.execute(select(RestApiCallRun).order_by(RestApiCallRun.started_at))).scalars().all())
