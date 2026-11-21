"""Channel placement across processes: polling only where the background workers run, reconciler changes from another process and devices reachable by their recent stamp."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime_toggles import DISABLE_BACKGROUND_WORKERS_ENV
from tests.worker_split_support import _FakeDb


class _Manager:
    """The reconciler's view of ``plugin_manager``, recording what it did."""

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
async def test_channel_reconciler_applies_changes_made_by_another_process(monkeypatch) -> None:
    from app.services.channel_config import runtime_sync

    rows = [SimpleNamespace(id=7, plugin_id="telegram", name="tg", project_id=None, enabled=True,
                            config={"bot_token": "a"})]

    async def _get_all(db):
        return list(rows)

    monkeypatch.setattr(runtime_sync.ChannelConfigService, "get_all", staticmethod(_get_all))
    manager = _Manager()

    assert (await runtime_sync.reconcile_channels(_FakeDb, manager))["started"] == 1
    assert (await runtime_sync.reconcile_channels(_FakeDb, manager))["unchanged"] == 1
    rows[0].config = {"bot_token": "b"}  # edited through another process
    assert (await runtime_sync.reconcile_channels(_FakeDb, manager))["reloaded"] == 1
    assert manager.loaded["7"]["bot_token"] == "b"
    rows[0].enabled = False  # disabled through another process
    assert (await runtime_sync.reconcile_channels(_FakeDb, manager))["stopped"] == 1
    assert manager.calls == [("reload", "7"), ("reload", "7"), ("stop", "7")]
    assert manager.applied == {}

    # The process that served the admin change applied the same configuration already: no second start.
    rows[0].enabled = True
    await manager.reload_channel("7", "telegram", runtime_sync.channel_runtime_config(rows[0]))
    assert (await runtime_sync.reconcile_channels(_FakeDb, manager))["unchanged"] == 1


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

    # Its socket was here and left: the stamp it wrote while here no longer counts (offline at once).
    connection = SimpleNamespace(device_id="d1", seat_login=False)
    await hub.attach(connection)
    assert hub.reachable(fresh) is True
    await hub.detach(connection)
    assert hub.reachable(fresh) is False
    fresh.last_seen_at = utc_now() + timedelta(seconds=1)  # it reconnected to another process since
    assert hub.reachable(fresh) is True
