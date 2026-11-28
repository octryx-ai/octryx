"""Shared helpers for the test_rest_connector_writes_* modules."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.models import ChangePreview, RestApiCallRun, User
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import create_definition, update_operation
from app.services.tool_approval.policy import platform_default, set_platform_default
from app.tools.definitions.rest_tool_classes import forget_rest_tools
from tests.support.rest_connector_support import API, SECRET, recorded_api

CREATE = "rest__desk__create_ticket"


UPDATE = "rest__desk__update_ticket"


LIST = "rest__desk__list_tickets"


BODY = {"required": True, "schema": {"type": "object", "properties": {
    "title": {"type": "string"}, "assignment_group": {"type": "string"}, "api_token": {"type": "string"}}}}


OPERATIONS = [
    {"op_key": "list_tickets", "method": "GET", "path": "/tickets",
     "parameters": [{"name": "assignment_group", "in": "query"}, {"name": "state", "in": "query"}]},
    {"op_key": "create_ticket", "method": "POST", "path": "/tickets", "request_body": BODY,
     "parameters": [{"name": "X-Request-Source", "in": "header"}]},
    {"op_key": "update_ticket", "method": "PUT", "path": "/tickets/{id}", "request_body": BODY,
     "parameters": [{"name": "id", "in": "path"}]},
]


WRITE_GRANT = {"role": "agent", "body_scope": {"assignment_group": "G1"}}


@pytest.fixture
def api(monkeypatch):
    return recorded_api(monkeypatch)


@pytest.fixture
def no_policy():
    saved = platform_default()
    set_platform_default({})
    yield
    set_platform_default(saved)


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _setup(db, *, grants=None, enable=("list_tickets", "create_ticket", "update_ticket"), extra=None,
                 connection=None):
    admin = await _admin(db)
    definition = await create_definition(db, {"key": "desk", "name": "Service Desk", "auth": {"scheme": "bearer"},
                                               "operations": OPERATIONS}, actor_user_id=admin.id)
    await create_connection(db, definition["id"], {"base_url": API, "token": SECRET, "name": "Desk prod",
                                                   **(connection or {})})
    operations = {operation["op_key"]: operation for operation in definition["operations"]}
    for op_key in enable:
        payload = {"enabled": True, "grants": [WRITE_GRANT] if grants is None else grants, **(extra or {})}
        if op_key == "list_tickets":
            payload = {"enabled": True, "grants": [{"role": grant["role"], **({"workspace_id": grant["workspace_id"]}
                                                                              if grant.get("workspace_id") else {})}
                                                   for grant in (grants or [WRITE_GRANT])]}
        await update_operation(db, definition["id"], operations[op_key]["id"], payload)
    return definition, operations


async def _runs(db) -> list[RestApiCallRun]:
    return list((await db.execute(select(RestApiCallRun).order_by(RestApiCallRun.started_at))).scalars().all())


async def _preview(db, preview_id: str) -> dict:
    row = (await db.execute(select(ChangePreview).where(ChangePreview.id == preview_id))).scalar_one()
    return json.loads(row.preview_json)


def _created(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json={"id": "T-1", **json.loads(request.content or b"{}")})


@pytest.fixture(autouse=True)
def fresh_view():
    forget_rest_tools()
    yield
    forget_rest_tools()
