"""Shared helpers for the test_rest_connector_odata_* modules."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import User
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import import_definition, update_operation
from app.tools.context import ToolContext
from tests.support.rest_connector_support import SECRET, recorded_api

FIXTURES = Path(__file__).parents[2] / "fixtures" / "odata"


SAP_ROOT = "https://s4.example.test/sap/opu/odata/sap/API_BUSINESS_PARTNER"


GRANT = [{"role": "agent"}]


@pytest.fixture
def api(monkeypatch):
    return recorded_api(monkeypatch)


def _sap(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


def _context(db, user_id: str) -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=["agent"], session_id="s-odata", project_config={},
                       db=db)


async def _import_sap(db, fixture: str, *, enable: tuple[str, ...]) -> dict:
    admin = await _admin(db)
    definition = await import_definition(db, {"key": "bp", "spec_text": _sap(fixture)}, actor_user_id=admin.id)
    await create_connection(db, definition["id"], {"base_url": SAP_ROOT, "username": "svc", "password": SECRET})
    for operation in definition["operations"]:
        if operation["op_key"] in enable:
            await update_operation(db, definition["id"], operation["id"], {"enabled": True, "grants": GRANT})
    return definition
