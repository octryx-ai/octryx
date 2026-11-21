"""Shared helpers for the test_named_connections_global_* modules."""

from __future__ import annotations

import json

from app.models import BuiltInToolConfig
from app.services.admin.project.named_connection_service import save_named
from tests.conftest import ADMIN_PASSWORD
from tests.knowledge_evidence_seed_support import seed_workspace

PANEL = "/admin/chat/api/panel"


WIKI = "https://wiki.example.test/wiki"


OTHER_WIKI = "https://other.example.test/wiki"


FAKE_A, FAKE_B, FAKE_G = "fake-pat-a-123", "fake-pat-b-456", "fake-pat-global-789"


def _body(name: str, scopes: list[str], token: str | None = None, url: str = WIKI) -> dict:
    body = {"name": name, "bound_scopes": scopes, "confluence_url": url, "confluence_auth_mode": "bearer_pat"}
    if token:
        body["confluence_token"] = token
    return body


def _no_secret(payload: object) -> None:
    text = json.dumps(payload)
    assert FAKE_A not in text and FAKE_B not in text and FAKE_G not in text and "_secret_ref" not in text


async def _workspace(db, *, active: bool = True, spaces=("ENG",)) -> str:
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=workspace_id, is_active=active, config={
        "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat", "confluence_token": "fake-default",
        "confluence_allowed_spaces": [{"space_key": key, "enabled": True} for key in spaces],
    }))
    await db.flush()
    return workspace_id


async def _save(db, project_id, body, connection_id=None) -> dict:
    return await save_named(db, connector="confluence", project_id=project_id, payload=body, actor_id=None,
                            connection_id=connection_id)


# --- global page: list, last test, usage ----------------------------------------------------------------


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303
