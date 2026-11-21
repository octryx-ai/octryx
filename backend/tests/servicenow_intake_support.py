"""Fixtures for the ServiceNow intake tests: a Workspace with a ServiceNow connection against the stub.

The stub (``servicenow_stub_support.StubInstance``) answers the password grant and the record listings; writes
(work notes) are recorded here. Every ServiceNow client's egress transport is the stub; no network.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select

import app.services.secure_work.servicenow.source as intake_source
import app.services.secure_work.servicenow.worknote as worknote_module
from app.models import BuiltInToolConfig, Project, User
from tests.servicenow_stub_support import CHANGES_PATH, INCIDENTS_PATH, StubInstance, config, record, stub_instance

TABLE_PATH = "/api/now/table/incident"


def incident(index: int, state: str, **extra) -> dict:
    return {**record(index), "state": {"display_value": state, "value": state.lower()}, **extra}


class WritingStub(StubInstance):
    """The ServiceNow stub plus recorded work-note writes (``PATCH`` table API, ``POST`` scripted path)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writes: list[tuple[str, str, dict]] = []
        self.write_status = 200

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method in ("PATCH", "POST") and request.url.path != "/oauth_token.do":
            import json

            self.writes.append((request.method, request.url.path, json.loads(request.content or b"{}")))
            if request.headers.get("Authorization") != f"Bearer {self.current}":
                return httpx.Response(401)
            return httpx.Response(self.write_status, json={"result": {}})
        return await super().handle(request)


def stub(monkeypatch, instance: StubInstance):
    for module in (intake_source, worknote_module):
        monkeypatch.setattr(module, "egress_transport", lambda *_a, inner=None, **_k: inner or instance.transport())
    yield from stub_instance(monkeypatch, instance)


async def workspace(db, **connection) -> tuple[str, User]:
    project = Project(name=f"sn-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="servicenow", project_id=project.id, config=config(**connection),
                             is_active=True))
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await db.commit()
    return project.id, admin


__all__ = ["CHANGES_PATH", "INCIDENTS_PATH", "TABLE_PATH", "WritingStub", "incident", "stub", "workspace"]
