"""Contract: a Workspace secret only ever goes to the Workspace's own target."""

from __future__ import annotations

import contextlib
import json
import uuid

import pytest

from app.models import BuiltInToolConfig
from app.services.connector_health import list_connector_health_rows
from app.services.knowledge.sources.sync.connections import resolve_connection
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.secret import set_secret_value
from app.services.tool_config import merge_tool_configs_into_project_config
from tests.egress_support import stub_settings, use_stub_settings
from tests.factories import make_project
from tests.services.connectors.test_workspace_connector_connection import BASIC, PASSWORD, USER, _stub

PANEL = "/admin/chat/api/panel"
TOKEN = "ws-jira-token"
BEARER = f"Bearer {TOKEN}"
CASES = {
    "confluence": (
        lambda url: {"confluence_url": url, "confluence_auth_mode": "basic", "confluence_username": USER},
        {"confluence_password": PASSWORD}, "confluence_url", BASIC,
    ),
    "jira": (
        lambda url: {"jira_url": url, "jira_auth_mode": "bearer_pat"},
        {"jira_token": TOKEN}, "jira_url", BEARER,
    ),
}
both = pytest.mark.parametrize("tool", list(CASES))


async def _project(db) -> str:
    return (await make_project(db, name=f"eff-{uuid.uuid4().hex[:8]}", commit=True)).id


@contextlib.asynccontextmanager
async def _two(monkeypatch):
    async with _stub() as (base_a, seen_a), _stub() as (base_b, seen_b):
        use_stub_settings(monkeypatch, stub_settings(
            hosts=",".join(base.removeprefix("http://") for base in (base_a, base_b))))
        yield base_a, seen_a, base_b, seen_b


async def _global(db, tool: str, url: str) -> None:
    unit, _, _, _ = CASES[tool]
    secret_field = "confluence_password" if tool == "confluence" else "jira_token"
    secret = await set_secret_value(db, tool_name=tool, field_name=secret_field, project_id=None, value="global-pw")
    db.add(BuiltInToolConfig(tool_name=tool, project_id=None, is_active=True,
                             config={**unit(url), f"{secret_field}_secret_ref": secret.id}))
    await db.commit()


async def _own(client, project_id: str, tool: str, url: str) -> str:
    unit, secret, _, _ = CASES[tool]
    route = f"{PANEL}/projects/{project_id}/connectors/{tool}/connection"
    saved = await client.put(route, json={"source": "workspace", **unit(url), **secret})
    assert saved.status_code == 200, saved.text
    return route


@both
async def test_clearing_the_workspace_target_never_moves_its_secret(admin_client, db, monkeypatch, tool):
    project_id = await _project(db)
    unit, _, target, credential = CASES[tool]
    async with _two(monkeypatch) as (base_a, _seen_a, base_b, seen_b):
        await _global(db, tool, base_b)
        route = await _own(admin_client, project_id, tool, base_a)

        cleared = await admin_client.post(f"{route}/test", json={"source": "workspace", target: ""})
        assert cleared.status_code == 422 and credential not in seen_b
        save = await admin_client.put(route, json={"source": "workspace", **unit("")})
        assert save.status_code == 422 and credential not in seen_b

        config = {key: value for key, value in unit(base_a).items() if key != target}
        legacy_form = {"tool_name": tool, "project_id": project_id, "config_json": json.dumps(config)}
        assert (await admin_client.post("/admin/tools/configs/test", data=legacy_form)).status_code == 409
        legacy_save = await admin_client.post("/admin/tools/configs/save", data={**legacy_form, "is_active": "true"})
        assert legacy_save.status_code == 409 and credential not in seen_b

        repoint = await admin_client.put(f"{PANEL}/connectors/{tool}", json={
            **unit(base_b), ("confluence_password" if tool == "confluence" else "jira_token"): "dummy"})
        assert repoint.status_code == 200, repoint.text
        assert (await admin_client.post(f"{route}/test", json={})).status_code == 200
        assert credential not in seen_b


@both
async def test_an_own_secret_without_an_own_target_fails_closed_at_runtime(admin_client, db, monkeypatch, tool):
    project_id = await _project(db)
    unit, secret, target, credential = CASES[tool]
    async with _two(monkeypatch) as (_base_a, _seen_a, base_b, seen_b):
        await _global(db, tool, base_b)
        (field, value), = secret.items()
        ref = await set_secret_value(db, tool_name=tool, field_name=field, project_id=project_id, value=value)
        own = {key: val for key, val in unit("x").items() if key != target}
        db.add(BuiltInToolConfig(tool_name=tool, project_id=project_id, is_active=True,
                                 config={**own, f"{field}_secret_ref": ref.id}))
        await db.commit()

        merged = await merge_tool_configs_into_project_config(db, project_id, {})
        assert not merged.get(target), "the global target is never combined with a Workspace secret"
        if tool == "confluence":
            with pytest.raises(ConnectorError) as refused:
                await resolve_connection(db, kind=tool, project_id=project_id)
            assert refused.value.reason == "own_connection_incomplete"
        tested = await admin_client.post(f"{PANEL}/projects/{project_id}/connectors/{tool}/connection/test", json={})
        assert tested.status_code == 422 and credential not in seen_b
        health = (await list_connector_health_rows(db))[(tool, project_id)]
        assert health.status == "error" and health.error.startswith("Own connection incomplete")
