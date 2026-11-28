"""Keep this process's channel plugins in line with the ``channel_configs`` rows."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .credentials import CHANNEL_START, UNUSABLE_SECRETS_KEY, channel_runtime_config
from .service import ChannelConfigService

logger = logging.getLogger(__name__)

DEFAULT_RECONCILE_SECONDS = 10.0


async def reconcile_channels(session_factory, manager: Any = None) -> dict[str, int]:
    if manager is None:
        from ...plugins import plugin_manager as manager
    counts = {"started": 0, "reloaded": 0, "stopped": 0, "blocked": 0, "unchanged": 0}
    async with session_factory() as db:
        channels = await ChannelConfigService.get_all(db)
        desired = {str(channel.id): channel for channel in channels if channel.enabled}
        for channel_id in sorted(manager.applied_channel_ids() - set(desired)):
            if manager.get_channel(channel_id) is not None:
                await manager.stop_channel(channel_id)
                counts["stopped"] += 1
                logger.info("Channel %s stopped (disabled or deleted)", channel_id)
            manager.forget_channel(channel_id)
        for channel_id, channel in desired.items():
            unresolved = await channel_runtime_config(db, channel, purpose=None)
            if manager.applied_fingerprint(channel_id) == manager.channel_fingerprint(channel.plugin_id, unresolved):
                counts["unchanged"] += 1
                continue
            was_loaded = manager.get_channel(channel_id) is not None
            try:
                runtime = await channel_runtime_config(db, channel, purpose=CHANNEL_START)
                await manager.reload_channel(channel_id, channel.plugin_id, runtime)
            except Exception:
                logger.exception("Failed to start channel '%s' (%s#%s)", channel.name, channel.plugin_id, channel.id)
                continue
            if runtime[UNUSABLE_SECRETS_KEY]:
                counts["blocked"] += 1
                logger.warning("Channel '%s' (%s#%s) unloaded: required secrets revoked or expired: %s",
                               channel.name, channel.plugin_id, channel.id, ", ".join(runtime[UNUSABLE_SECRETS_KEY]))
                continue
            counts["reloaded" if was_loaded else "started"] += 1
            if manager.get_channel(channel_id) is not None:
                logger.info("Channel '%s' (%s#%s) started", channel.name, channel.plugin_id, channel.id)
            else:
                logger.warning("Channel '%s' (%s#%s) could not be started", channel.name, channel.plugin_id,
                               channel.id)
    return counts


class ChannelReconciler:
    def __init__(self, session_factory, *, interval_seconds: float = DEFAULT_RECONCILE_SECONDS) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def reconcile_once(self) -> dict[str, int] | None:
        try:
            return await reconcile_channels(self._session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next pass applies the same rule again
            logger.warning("channel_reconcile_failed", extra={"error_type": type(exc).__name__})
            return None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="channel-reconciler")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self.reconcile_once()


__all__ = ["DEFAULT_RECONCILE_SECONDS", "ChannelReconciler", "reconcile_channels"]
