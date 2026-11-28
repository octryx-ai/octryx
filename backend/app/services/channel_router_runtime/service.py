"""Channel message router service implementation."""

import asyncio
import logging

from app.services.error_facts import error_text

from .approval_commands import handle_approval_command
from .channel_sessions import ChannelSessionsMixin
from .message_turns import ChannelTurnsMixin

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.1  # seconds between full plugin poll sweeps


class ChannelMessageRouter(ChannelTurnsMixin, ChannelSessionsMixin):
    """Background service that: 1."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._session_factory = None
        self._session_cache: dict[str, str] = {}  # channel_key -> session.id

    async def start(self, session_factory) -> None:
        self._session_factory = session_factory
        self._task = asyncio.create_task(self._routing_loop())
        logger.info("Channel message router started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Channel message router stopped")

    async def _routing_loop(self) -> None:
        while True:
            try:
                from ...plugins import plugin_manager

                for channel_id, plugin in plugin_manager.iter_channels():
                    try:
                        msg = await plugin.receive_message()
                        if msg:
                            asyncio.create_task(self._handle_message(channel_id, plugin, msg))
                    except Exception as exc:
                        logger.error("Error polling channel %s: %s", channel_id, error_text("channel_poll_failed", exc))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Channel router sweep error: %s", error_text("channel_router_sweep_failed", exc))
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_proactive_reply(
        self,
        db,
        conversation_id: str,
        content: str,
        sender_id: str,
        plugin,
        msg: dict,
    ) -> bool:
        try:
            from ..proactive_teams.reply_handler import check_proactive_reply, process_proactive_reply

            match = await check_proactive_reply(db, conversation_id, content, sender_id)
            if not match:
                return False

            # Process the reply (comment on Jira, resume agent session)
            confirmation = await process_proactive_reply(db, match)
            if confirmation:
                target = str(msg.get("target") or sender_id)
                await plugin.send_message(target, confirmation)

            return True
        except Exception as exc:
            logger.warning("Error checking proactive reply: %s", error_text("proactive_reply_check_failed", exc))
            return False

    async def _handle_approval_command(self, db, content: str, sender_user_id: str | None) -> str | None:
        return await handle_approval_command(db, content, sender_user_id, session_factory=self._session_factory)


channel_message_router = ChannelMessageRouter()

__all__ = ["POLL_INTERVAL", "ChannelMessageRouter", "channel_message_router"]
