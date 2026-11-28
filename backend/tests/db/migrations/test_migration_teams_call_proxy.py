from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from tests.alembic_model_parity_support import (
    DIALECTS,
    ScratchDatabase,
    alembic_version,
    assert_exact_residual,
    head_revision,
    schema_drift,
    scratch_database,
)
from tests.support.alembic_model_parity_residual import expected_residual
from tests.support.alembic_upgrade_support import insert_row, upgraded_database

PREVIOUS_REVISION = "a0007audit_workspace"
WORKSPACE, AGENT = "workspace-0001", "call-agent-0001"
TEAMS_CONFIG = {"calling_enabled": True, "calling_public_ws_url": "wss://calls.example",
                "calling_webhook_url": "https://proxy.example/incoming-call"}
SLACK_CONFIG = {"calling_webhook_url": "https://other.example/kept"}


def _seed(connection: Connection) -> None:
    insert_row(connection, "projects", id=WORKSPACE, name="demo-shop", source_type="local", is_system=False,
               access_mode="private")
    insert_row(connection, "call_agent_configs", id=AGENT, name="Front desk", project_id=WORKSPACE,
               calling_webhook_url="https://proxy.example/incoming-call", system_prompt="Answer briefly.",
               thinking_message="One moment.")
    insert_row(connection, "channel_configs", id=1, plugin_id="msteams", name="Calls", project_id=WORKSPACE,
               enabled=True, config=json.dumps(TEAMS_CONFIG))
    insert_row(connection, "channel_configs", id=2, plugin_id="slack", name="Chat", project_id=WORKSPACE,
               enabled=True, config=json.dumps(SLACK_CONFIG))
    insert_row(connection, "channel_configs", id=3, plugin_id="msteams", name="Broken", project_id=WORKSPACE,
               enabled=False, config="not json")


def _call_agent(connection: Connection) -> dict:
    row = connection.execute(sa.text("SELECT * FROM call_agent_configs WHERE id = :id"), {"id": AGENT}).mappings()
    return dict(row.one())


def _channel_configs(connection: Connection) -> dict[int, str]:
    return dict(connection.execute(sa.text("SELECT id, config FROM channel_configs ORDER BY id")).tuples().all())


def _call_agent_columns(connection: Connection) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns("call_agent_configs")}


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-a0007"), _seed,
                           revision=PREVIOUS_REVISION) as database:
        yield database


def test_the_upgrade_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_the_upgrade_drops_the_call_agent_webhook_url_and_keeps_the_agent(upgraded: ScratchDatabase) -> None:
    agent = upgraded.run(_call_agent)
    assert "calling_webhook_url" not in agent
    assert (agent["name"], agent["project_id"], agent["thinking_message"]) == ("Front desk", WORKSPACE, "One moment.")


def test_the_upgrade_drops_the_webhook_url_from_teams_channels_only(upgraded: ScratchDatabase) -> None:
    configs = upgraded.run(_channel_configs)
    expected_teams = {key: value for key, value in TEAMS_CONFIG.items() if key != "calling_webhook_url"}
    assert json.loads(configs[1]) == expected_teams
    assert json.loads(configs[2]) == SLACK_CONFIG
    assert configs[3] == "not json"


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_restores_the_empty_column(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=PREVIOUS_REVISION, down=True)
        assert "calling_webhook_url" in database.run(_call_agent_columns)
        assert database.run(_call_agent)["calling_webhook_url"] is None
