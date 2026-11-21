"""Slack channel plugin for Octryx."""

import asyncio
import logging
from typing import Any

import httpx

from ..core.base import ChannelPlugin

logger = logging.getLogger(__name__)

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"


class SlackPlugin(ChannelPlugin):
    """
    Slack channel plugin using Slack Events API and Web API.
    Receives messages via webhook (Events API); sends via chat.postMessage.
    """

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        super().__init__(plugin_id, config)
        self.bot_token: str = config.get("bot_token", "")
        self.signing_secret: str = config.get("signing_secret", "")
        self.dm_policy: str = config.get("dm_policy", "open")
        self.allow_from: list[str] = config.get("allow_from", [])
        self.require_mention: bool = config.get("require_mention", False)

        # RBAC fields
        self.require_registered_user: bool = config.get("require_registered_user", False)
        self.allowed_roles: list[str] = config.get("allowed_roles", [])
        self.sender_mappings: dict = {}
        raw = config.get("sender_mappings", "")
        if raw and isinstance(raw, str):
            import json as _json

            self.sender_mappings = _json.loads(raw)
        elif isinstance(raw, dict):
            self.sender_mappings = raw

        # Internal state
        self._http_client: httpx.AsyncClient | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue()

    # ----------------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token is required for Slack plugin")
        if not self.signing_secret:
            raise ValueError("signing_secret is required for Slack plugin")

        self._http_client = httpx.AsyncClient(timeout=30.0)
        try:
            resp = await self._http_client.get(
                _SLACK_AUTH_TEST_URL,
                headers={"Authorization": f"Bearer {self.bot_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise ValueError(f"Slack auth.test failed: {data.get('error', 'unknown')}")
            logger.info(
                "Slack plugin initialised as team=%s bot_id=%s",
                data.get("team"),
                data.get("bot_id"),
            )
        except Exception:
            logger.exception("Slack plugin: failed to verify token")
            await self._http_client.aclose()
            self._http_client = None
            raise

    async def shutdown(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Slack plugin shut down")

    # ----------------------------------------------------------------- send

    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """Send a message to a Slack channel or user (by channel/user ID)."""
        if not self._http_client:
            logger.error("Slack plugin: not initialised")
            return False

        try:
            resp = await self._http_client.post(
                _SLACK_POST_MESSAGE_URL,
                headers={
                    "Authorization": f"Bearer {self.bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"channel": target, "text": content},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Slack send_message error: {data.get('error')}")
                return False
            logger.debug(f"Slack message sent to {target}")
            return True
        except Exception as e:
            logger.exception(f"Slack send_message error: {e}")
            return False

    # ----------------------------------------------------------------- receive

    async def receive_message(self) -> dict[str, Any] | None:
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ----------------------------------------------------------------- webhook

    async def receive_webhook(self, payload: dict) -> None:
        """
        Called when Slack Events API posts to our endpoint.
        Extracts message events and queues them.
        """
        event = payload.get("event", {})
        event_type = event.get("type", "")

        if event_type != "message":
            return

        # Skip messages with subtypes (e.g. bot_message, message_changed)
        if event.get("subtype"):
            return

        text = event.get("text", "")
        sender_id = event.get("user", "")
        channel = event.get("channel", "")
        ts = event.get("ts", "")
        channel_type = event.get("channel_type", "")

        if not text or not sender_id:
            return

        # DM policy check
        if channel_type == "im":
            if self.dm_policy == "disabled":
                return
            if self.dm_policy == "allowlist" and sender_id not in self.allow_from:
                return

        message = {
            "sender_id": sender_id,
            "content": text,
            "target": channel,
            "timestamp": ts,
            "raw": payload,
            "channel_type": channel_type,
        }
        await self._message_queue.put(message)
        logger.debug(f"Slack message queued from {sender_id} in {channel}")

    # Inbound request signatures are verified in services/channel_webhook_auth.

    # ----------------------------------------------------------------- info

    def get_plugin_info(self) -> dict[str, Any]:
        return {
            "id": "slack",
            "name": "Slack",
            "description": "Slack channel plugin for sending and receiving messages via Slack Events API",
            "version": "0.1.0",
            "author": "Octryx",
            "config_fields": [
                {
                    "name": "bot_token",
                    "type": "string",
                    "secret": True,
                    "required": True,
                    "description": "Slack Bot Token (xoxb-...)",
                },
                {
                    "name": "signing_secret",
                    "type": "string",
                    "secret": True,
                    "required": True,
                    "description": "Slack Signing Secret for request verification",
                },
                {
                    "name": "dm_policy",
                    "type": "select",
                    "options": ["open", "allowlist", "disabled"],
                    "default": "open",
                    "description": "Policy for direct messages",
                },
                {
                    "name": "allow_from",
                    "type": "list",
                    "default": [],
                    "description": "Allowed Slack user IDs for DMs when dm_policy is 'allowlist'",
                },
                {
                    "name": "require_mention",
                    "type": "boolean",
                    "default": False,
                    "description": "Only respond to messages that @mention the bot in channels",
                },
                {
                    "name": "default_target",
                    "type": "string",
                    "default": "",
                    "description": "Default Slack channel ID used for proactive task output delivery, e.g. C0123456789",
                },
                {
                    "name": "require_registered_user",
                    "type": "boolean",
                    "default": False,
                    "description": "Only respond to senders mapped to an Octryx user",
                },
                {
                    "name": "sender_mappings",
                    "type": "string",
                    "default": "",
                    "description": 'JSON object mapping external sender IDs to platform user IDs, e.g. {"U12345": "user-uuid"}',
                },
                {
                    "name": "allowed_roles",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated role names allowed to use this channel (empty = all roles)",
                },
            ],
        }
