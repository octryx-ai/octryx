"""A Workspace's own connection that is incomplete says so without a test: ``state`` comes from the stored
entry, and a Knowledge run on it fails with ``own_connection_incomplete``."""

from __future__ import annotations

import pytest

from app.models import BuiltInToolConfig
from app.services.knowledge.sources.sync.connections import resolve_connection
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.secret import set_secret_value
from tests.services.connectors.test_workspace_connector_connection import PANEL, USER, _login, _project

INCOMPLETE = "Own connection incomplete: set its URL, auth mode and credential, or use the global connection."
DISABLED = "Own connection disabled for this Workspace: enable the connector in its access settings."


async def _entry(db, project_id: str | None, config: dict, *, password: str | None = None, active: bool = True) -> None:
    if password is not None:
        secret = await set_secret_value(db, tool_name="confluence", field_name="confluence_password",
                                        project_id=project_id, value=password)
        config = {**config, "confluence_password_secret_ref": secret.id}
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project_id, is_active=active, config=config))
    await db.commit()


OWN_UNIT = {"confluence_auth_mode": "basic", "confluence_username": USER}


@pytest.mark.parametrize(
    ("config", "password", "state"),
    [
        (OWN_UNIT, "pw", "own_incomplete"),  # own secret, URL gone
        ({**OWN_UNIT, "confluence_url": "https://wiki.example.test/wiki"}, None, "own_incomplete"),
        ({**OWN_UNIT, "confluence_url": "https://wiki.example.test/wiki"}, "pw", "own"),
        ({"confluence_allowed_spaces": ["ENG"]}, None, "global"),
    ],
)
async def test_the_connection_read_computes_its_state_without_a_test(client, db, config, password, state):
    await _login(client)
    project_id = await _project(db)
    await _entry(db, project_id, config, password=password)

    body = (await client.get(f"{PANEL}/projects/{project_id}/connectors/confluence/connection")).json()

    assert (body["state"], body["health"]) == (state, None)
    assert body["state_summary"] == (INCOMPLETE if state == "own_incomplete" else None)


@pytest.mark.parametrize(
    ("config", "password", "with_global", "reason"),
    [
        # A usable global connection exists, yet the own unit never falls back to it.
        (OWN_UNIT, "pw", True, "own_connection_incomplete"),
        ({**OWN_UNIT, "confluence_url": "https://wiki.example.test/wiki"}, None, True, "own_connection_incomplete"),
        ({"confluence_allowed_spaces": ["ENG"]}, None, False, "connection_not_configured"),
    ],
)
async def test_a_run_names_an_incomplete_own_connection(db, config, password, with_global, reason):
    project_id = await _project(db)
    if with_global:
        await _entry(db, None, {"confluence_url": "https://global.example.test/wiki", **OWN_UNIT}, password="g")
    await _entry(db, project_id, config, password=password)

    with pytest.raises(ConnectorError) as refused:
        await resolve_connection(db, kind="confluence", project_id=project_id)

    assert refused.value.reason == reason



@pytest.mark.parametrize("config", [OWN_UNIT, {**OWN_UNIT, "confluence_url": "https://wiki.example.test/wiki"}])
async def test_a_disabled_own_entry_is_reported_as_disabled_not_incomplete(client, db, config):
    await _login(client)
    project_id = await _project(db)
    await _entry(db, project_id, config, password="pw", active=False)

    body = (await client.get(f"{PANEL}/projects/{project_id}/connectors/confluence/connection")).json()

    assert (body["state"], body["state_summary"]) == ("own_disabled", DISABLED)
