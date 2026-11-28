from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import ChannelConfig, SecretAccessAuditLog
from app.plugins.channels.slack_plugin import SlackPlugin
from app.plugins.channels.teams_plugin import TeamsPlugin
from app.plugins.channels.telegram import TelegramPlugin
from app.services.channel_config.credentials import CHANNEL_START, channel_runtime_config
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
from tests.support.alembic_upgrade_support import BASELINE_REVISION, insert_row, upgraded_database

WORKSPACE = "workspace-0001"
TEAMS_PASSWORD = "Synthetic~Teams.Pass-QXZW11"
SLACK_TOKEN = "xoxb-" "0000000011-0000000012-SyntheticSlackQXZW"  # split so secret scanners do not flag the synthetic fixture
SLACK_SIGNING = "synthetic-slack-signing-QXZW13"
TELEGRAM_TOKEN = "100000011:A" + "Synthetic_Telegram-" + "x" * 15
CHANNELS = {
    1: ("msteams", {"app_id": "app-0011", "app_password": TEAMS_PASSWORD, "tenant_id": "tenant-0011"}),
    2: ("slack", {"bot_token": SLACK_TOKEN, "signing_secret": SLACK_SIGNING, "default_target": "#ops"}),
    3: ("telegram", {"bot_token": TELEGRAM_TOKEN, "polling_interval": 2}),
}
PLAIN = (TEAMS_PASSWORD, SLACK_TOKEN, SLACK_SIGNING, TELEGRAM_TOKEN)


def _seed_0_0_1(connection: Connection) -> None:
    insert_row(connection, "projects", id=WORKSPACE, name="demo-shop", source_type="local", is_system=False,
               access_mode="private")
    for channel_id, (plugin_id, config) in CHANNELS.items():
        insert_row(connection, "channel_configs", id=channel_id, plugin_id=plugin_id, name=f"demo-{plugin_id}",
                   project_id=WORKSPACE, enabled=True, config=json.dumps(config))


def _channel_configs(connection: Connection) -> dict[int, dict]:
    rows = connection.execute(sa.text("SELECT id, config FROM channel_configs ORDER BY id"))
    return {channel_id: json.loads(config) for channel_id, config in rows}


@pytest.fixture(scope="module", params=DIALECTS)
def upgraded(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScratchDatabase]:
    with upgraded_database(request.param, tmp_path_factory.mktemp("upgrade-channel-secrets"), _seed_0_0_1) as db:
        yield db


def test_the_upgrade_from_0_0_1_reaches_head(upgraded: ScratchDatabase) -> None:
    assert upgraded.run(alembic_version) == head_revision()


def test_the_upgrade_leaves_no_plain_channel_secret_and_keeps_the_other_fields(upgraded: ScratchDatabase) -> None:
    configs = upgraded.run(_channel_configs)
    assert not any(value in json.dumps(configs) for value in PLAIN)
    assert configs[1]["app_id"] == "app-0011" and configs[2]["default_target"] == "#ops"
    assert set(configs[2]) == {"bot_token_secret_ref", "signing_secret_secret_ref", "default_target"}
    stored = upgraded.run(lambda connection: list(connection.execute(sa.text(
        "SELECT tool_name, field_name, project_id, encrypted_value FROM stored_secrets "
        "WHERE tool_name LIKE 'channel:%' ORDER BY tool_name, field_name")).tuples()))
    assert [(tool, field, workspace) for tool, field, workspace, _value in stored] == [
        ("channel:1", "app_password", WORKSPACE), ("channel:2", "bot_token", WORKSPACE),
        ("channel:2", "signing_secret", WORKSPACE), ("channel:3", "bot_token", WORKSPACE)]
    assert all(value.startswith("fernet:") for *_rest, value in stored)


async def _start_each_channel(url: str) -> dict[str, object]:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            channels = (await db.execute(sa.select(ChannelConfig).order_by(ChannelConfig.id))).scalars().all()
            plugins = {}
            for channel, plugin_class in zip(channels, (TeamsPlugin, SlackPlugin, TelegramPlugin), strict=True):
                plugins[channel.plugin_id] = plugin_class(str(channel.id), await channel_runtime_config(
                    db, channel, purpose=CHANNEL_START))
            await db.commit()
            audited = (await db.execute(sa.select(SecretAccessAuditLog.purpose, SecretAccessAuditLog.project_id)
                                        )).all()
        return {"plugins": plugins, "audited": audited}
    finally:
        await engine.dispose()


def test_a_channel_created_before_the_upgrade_starts_with_its_decrypted_credentials(upgraded: ScratchDatabase,
                                                                                    tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        started = asyncio.run(_start_each_channel(database.url))
    plugins = started["plugins"]
    assert plugins["msteams"].app_password == TEAMS_PASSWORD
    assert (plugins["slack"].bot_token, plugins["slack"].signing_secret) == (SLACK_TOKEN, SLACK_SIGNING)
    assert plugins["telegram"].bot_token == TELEGRAM_TOKEN
    assert sorted(started["audited"]) == [(CHANNEL_START, WORKSPACE)] * 4


def test_the_upgraded_schema_matches_the_models(upgraded: ScratchDatabase) -> None:
    assert_exact_residual(upgraded.run(schema_drift), expected_residual(upgraded.dialect))


def test_the_downgrade_puts_the_plain_values_back(upgraded: ScratchDatabase, tmp_path: Path) -> None:
    with scratch_database(upgraded.dialect, tmp_path, template=upgraded) as database:
        with pytest.MonkeyPatch.context() as monkeypatch:
            database.migrate(monkeypatch, revision=BASELINE_REVISION, down=True)
        assert database.run(_channel_configs) == {channel_id: config for channel_id, (_p, config) in CHANNELS.items()}
