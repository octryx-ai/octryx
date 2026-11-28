"""Shared helpers for the test_knowledge_source_sync_custom_rest_* modules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.models import Project, Role, User, UserRole
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import create_definition, update_operation
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.rest_connector_support import API, SECRET, recorded_api

OPERATIONS = [
    {"op_key": "list_docs", "method": "GET", "path": "/docs",
     "parameters": [{"name": "group", "in": "query"}, {"name": "changed_since", "in": "query"}]},
    {"op_key": "get_doc", "method": "GET", "path": "/docs/{id}", "parameters": [{"name": "id", "in": "path"}]},
]


MAPPING = {"id": "id", "title": "title", "url": "link", "updated_at": "updated", "content": "body"}


@pytest.fixture
def api(monkeypatch):
    return recorded_api(monkeypatch)


class FakeDocs:
    def __init__(self, page_size: int = 50) -> None:
        self.docs: dict[str, dict] = {}
        self.page_size = page_size

    def put(self, doc_id: str, title: str, body: str, *, group: str = "G1", updated: str = "2026-11-10T10:00:00Z"):
        self.docs[doc_id] = {"id": doc_id, "title": title, "group": group, "updated": updated, "body": body,
                             "link": f"https://desk.example.test/d/{doc_id}"}

    def answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        if path.startswith("/docs/"):
            doc = self.docs[path.removeprefix("/docs/")]
            return httpx.Response(200, json=doc)
        rows = [{key: value for key, value in doc.items() if key != "body"} for _, doc in sorted(self.docs.items())]
        start = int(request.url.params.get("cursor") or 0)
        end = start + self.page_size
        return httpx.Response(200, json={"items": rows[start:end], "next": str(end) if end < len(rows) else None})


async def _platform_role(db, user_id: str, name: str) -> None:
    role = Role(name=name)
    db.add(role)
    await db.flush()
    db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.flush()


async def _world(db, *, enforce: bool = True, list_grants=None) -> SimpleNamespace:
    suffix = uuid.uuid4().hex[:6]
    roles = SimpleNamespace(agent=f"kagent{suffix}", other=f"kother{suffix}")
    workspace_id = await seed_workspace(db)
    if enforce:
        project = await db.get(Project, workspace_id)
        project.config = {"knowledge_source_acl": {"enforce": True}}
    alice_id = await seed_member(db, workspace_id=workspace_id, role="admin", username=f"alice{suffix}")
    bob_id = await seed_member(db, workspace_id=workspace_id, role="member", username=f"bob{suffix}")
    await _platform_role(db, alice_id, roles.agent)
    await _platform_role(db, bob_id, roles.other)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    key = f"k{suffix}"
    definition = await create_definition(db, {"key": key, "name": "Desk docs", "auth": {"scheme": "bearer"},
                                               "operations": OPERATIONS}, actor_user_id=admin.id)
    await create_connection(db, definition["id"], {"base_url": API, "token": SECRET})
    operations = {operation["op_key"]: operation for operation in definition["operations"]}
    scoped = [{"role": roles.agent, "scope": {"group": "G1"}, "result_filter": {"field": "group", "value": "G1"}},
              {"role": roles.other, "scope": {"group": "G2"}}]
    await update_operation(db, definition["id"], operations["list_docs"]["id"], {
        "enabled": True, "grants": scoped if list_grants is None else list_grants(roles),
        "pagination": {"type": "cursor", "cursor_path": "next", "cursor_param": "cursor"}, "records_path": "items"})
    await update_operation(db, definition["id"], operations["get_doc"]["id"], {
        "enabled": True, "grants": [{"role": roles.agent}, {"role": roles.other}]})
    alice = await authorize_workspace(db, current_user=await fetch_user(db, alice_id), workspace_id=workspace_id)
    bob = await authorize_workspace(db, current_user=await fetch_user(db, bob_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    await db.commit()
    return SimpleNamespace(alice=alice, bob=bob, alice_id=alice_id, key=key, roles=roles, runtime=runtime,
                           workspace_id=workspace_id)


def _scope(world, **extra) -> dict:
    return {"definition": world.key, "operation": "list_docs", "role": world.roles.agent,
            "detail_operation": "get_doc", **extra}


async def _run(db, world, row):
    row = await db.get(KnowledgeSourceConnector, row.id)
    run = await run_connector(db, runtime=world.runtime, authorized=world.alice, row=row, actor_id=world.alice_id)
    projector = EvidenceProjector(world.runtime)
    while await projector.project_once(db, worker_id="test") is not None:
        pass
    return run
