"""Channel placement across processes: polling only where the background workers run, reconciler changes from another process and devices reachable by their recent stamp."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV


class _Manager:
    def __init__(self) -> None:
        from app.plugins import _PluginManager

        self._fingerprint = _PluginManager.channel_fingerprint
        self.loaded: dict[str, dict] = {}
        self.applied: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    def channel_fingerprint(self, plugin_id, config):
        return self._fingerprint(plugin_id, config)

    def applied_fingerprint(self, channel_id):
        return self.applied.get(channel_id)

    def applied_channel_ids(self):
        return set(self.applied) | set(self.loaded)

    def forget_channel(self, channel_id):
        self.applied.pop(channel_id, None)

    def get_channel(self, channel_id):
        return self.loaded.get(channel_id)

    async def stop_channel(self, channel_id):
        self.calls.append(("stop", channel_id))
        self.loaded.pop(channel_id, None)

    async def reload_channel(self, channel_id, plugin_id, config):
        self.calls.append(("reload", channel_id))
        self.applied[channel_id] = self.channel_fingerprint(plugin_id, config)
        self.loaded[channel_id] = config


def test_polling_channels_receive_only_where_the_background_workers_run(monkeypatch) -> None:
    from app.plugins import _PluginManager

    manager = _PluginManager()
    config = {"enabled": True, "bot_token": "t", "signing_secret": "s"}

    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "1")  # an API process of a split deployment
    assert manager.load_channel("1", "telegram", dict(config)).inbound_enabled is False
    assert manager.load_channel("2", "slack", dict(config)).inbound_enabled is True

    monkeypatch.setenv(DISABLE_BACKGROUND_WORKERS_ENV, "0")  # the platform worker or a single process
    assert manager.load_channel("3", "telegram", dict(config)).inbound_enabled is True
    assert manager.load_channel("4", "email", {"enabled": True}).inbound_enabled is True


@pytest.mark.asyncio
async def test_polling_plugin_loaded_for_sending_starts_no_poll_loop() -> None:
    from app.plugins.channels.telegram import TelegramPlugin

    plugin = TelegramPlugin("telegram", {"enabled": True, "bot_token": "t", "__inbound": False})

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True, "result": {"username": "bot"}}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def get(self, url):
            return _Response()

        async def aclose(self) -> None:
            return None

    import app.plugins.channels.telegram as telegram_module

    original = telegram_module.httpx.AsyncClient
    telegram_module.httpx.AsyncClient = _Client
    try:
        await plugin.initialize()
    finally:
        telegram_module.httpx.AsyncClient = original
    assert plugin._polling_task is None


@pytest.mark.asyncio
async def test_channel_reconciler_applies_changes_made_by_another_process(db) -> None:
    from app.services.channel_config import ChannelConfigService, runtime_sync
    from app.services.channel_config.credentials import CHANNEL_START, channel_runtime_config

    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    created = await ChannelConfigService.create(db, plugin_id="telegram", name="tg", project_id=None, enabled=True,
                                                config={"bot_token": "a"})
    channel_id = str(created.id)
    manager = _Manager()

    assert (await runtime_sync.reconcile_channels(_Session, manager))["started"] == 1
    assert manager.loaded[channel_id]["bot_token"] == "a"
    assert (await runtime_sync.reconcile_channels(_Session, manager))["unchanged"] == 1
    await ChannelConfigService.update(db, created.id, config={"bot_token": "b"})
    assert (await runtime_sync.reconcile_channels(_Session, manager))["reloaded"] == 1
    assert manager.loaded[channel_id]["bot_token"] == "b"
    await ChannelConfigService.update(db, created.id, enabled=False)
    assert (await runtime_sync.reconcile_channels(_Session, manager))["stopped"] == 1
    assert [call for call in manager.calls if call[1] == channel_id] == [
        ("reload", channel_id), ("reload", channel_id), ("stop", channel_id)]
    assert channel_id not in manager.applied

    updated = await ChannelConfigService.update(db, created.id, enabled=True)
    await manager.reload_channel(channel_id, "telegram", await channel_runtime_config(db, updated,
                                                                                      purpose=CHANNEL_START))
    assert (await runtime_sync.reconcile_channels(_Session, manager))["unchanged"] >= 1
    assert manager.calls.count(("reload", channel_id)) == 3


@pytest.mark.asyncio
async def test_a_device_connected_to_another_process_is_reachable_by_its_recent_stamp() -> None:
    from datetime import timedelta

    from app.services.devices.hub import REMOTE_LIVE_WINDOW, DeviceHub
    from app.time_utils import utc_now

    hub = DeviceHub()
    fresh = SimpleNamespace(id="d1", last_seen_at=utc_now() - timedelta(seconds=10))
    stale = SimpleNamespace(id="d2", last_seen_at=utc_now() - REMOTE_LIVE_WINDOW - timedelta(seconds=1))
    never = SimpleNamespace(id="d3", last_seen_at=None)
    assert (hub.reachable(fresh), hub.reachable(stale), hub.reachable(never)) == (True, False, False)

    connection = SimpleNamespace(device_id="d1", seat_login=False)
    await hub.attach(connection)
    assert hub.reachable(fresh) is True
    await hub.detach(connection)
    assert hub.reachable(fresh) is False
    fresh.last_seen_at = utc_now() + timedelta(seconds=1)
    assert hub.reachable(fresh) is True
