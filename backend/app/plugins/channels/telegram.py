import asyncio
import logging
from typing import Any

import httpx

from ...services.error_facts import error_text
from ..core.base import ChannelPlugin

logger = logging.getLogger(__name__)


class TelegramPlugin(ChannelPlugin):
    """Telegram Bot API plugin for Octryx."""

    INBOUND_POLLING = True

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        super().__init__(plugin_id, config)
        self.bot_token: str | None = config.get("bot_token")
        self.polling_interval: float = config.get("polling_interval", 1.0)
        self.allowed_users: list[str] = config.get("allowed_users", [])
        self.audit_enabled: bool = config.get("auditEnabled", False)
        self.require_mention: bool = config.get("requireMention", True)
        self.dm_policy: str = config.get("dmPolicy", "pairing")  # pairing, allowlist, open, disabled
        self.allow_from: list[str] = config.get("allowFrom", [])

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
        self._base_url: str = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
        self._offset: int = 0
        self._polling_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._http_client: httpx.AsyncClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Telegram plugin."""
        if not self.bot_token:
            logger.error("Telegram plugin: bot_token is required")
            raise ValueError("bot_token is required for Telegram plugin")

        self._http_client = httpx.AsyncClient(timeout=30.0)
        # Test the bot token
        try:
            resp = await self._http_client.get(f"{self._base_url}/getMe")
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise Exception(f"Failed to get bot info: {data}")
            logger.info(f"Telegram plugin initialized as @{data['result']['username']}")
        except Exception as exc:
            # An httpx error names the request URL, and the Bot API carries the token in its path.
            failure = error_text("telegram_start_failed", exc)
            logger.warning("Failed to initialize Telegram plugin: %s", failure)
            await self._http_client.aclose()
            self._http_client = None
            raise RuntimeError(failure) from None

        # Start the polling task (only where inbound runs: the background-worker process)
        if not self.inbound_enabled:
            logger.info("Telegram plugin initialized for sending only (inbound polling runs elsewhere)")
            return
        self._polling_task = asyncio.create_task(self._polling_loop())
        logger.info("Telegram plugin polling task started")

    async def shutdown(self) -> None:
        """Shutdown the Telegram plugin."""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.exception(f"Error stopping Telegram polling task: {e}")
            finally:
                self._polling_task = None

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("Telegram plugin shut down")

    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """Send a message to a target (user_id, chat_id, etc.) via Telegram."""
        if not self._http_client:
            logger.error("Telegram plugin: not initialized")
            return False

        try:
            resp = await self._http_client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": target,
                    "text": content,
                    "parse_mode": "HTML",  # We'll use HTML for basic formatting
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                logger.debug(f"Telegram message sent to {target}")
                return True
            else:
                logger.error(f"Failed to send Telegram message: {data}")
                return False
        except Exception as e:
            logger.warning("Error sending Telegram message to %s: %s", target, error_text("telegram_send_failed", e))
            return False

    async def receive_message(self) -> dict[str, Any] | None:
        """Receive a message from the Telegram plugin's internal queue."""
        try:
            # Non-blocking get
            message = self._message_queue.get_nowait()
            return message
        except asyncio.QueueEmpty:
            return None

    def get_plugin_info(self) -> dict[str, Any]:
        """Return metadata about the Telegram plugin."""
        return {
            "id": "telegram",
            "name": "Telegram Bot",
            "description": "Telegram Bot API plugin for sending and receiving messages",
            "version": "0.1.0",
            "author": "Octryx",
            "config_fields": [
                {"name": "bot_token", "type": "string", "secret": True, "required": True, "description": "Telegram Bot Token"},
                {
                    "name": "polling_interval",
                    "type": "number",
                    "default": 1.0,
                    "description": "Polling interval in seconds",
                },
                {
                    "name": "allowed_users",
                    "type": "list",
                    "items": {"type": "string"},
                    "description": "List of allowed user IDs (Telegram user IDs)",
                },
                {
                    "name": "auditEnabled",
                    "type": "boolean",
                    "default": False,
                    "description": "Enable audit logging for this channel",
                },
                {
                    "name": "requireMention",
                    "type": "boolean",
                    "default": True,
                    "description": "Only respond to messages that mention the bot",
                },
                {
                    "name": "dmPolicy",
                    "type": "string",
                    "default": "pairing",
                    "options": ["pairing", "allowlist", "open", "disabled"],
                    "description": "Policy for direct messages",
                },
                {
                    "name": "allowFrom",
                    "type": "list",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "List of allowed sender IDs for DMs (when dmPolicy is allowlist)",
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
                    "description": 'JSON object mapping external sender IDs to platform user IDs, e.g. {"123": "user-uuid"}',
                },
                {
                    "name": "allowed_roles",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated list of role names allowed to use this channel (empty = all roles)",
                },
            ],
        }

    async def _polling_loop(self) -> None:
        logger.info("Telegram polling loop started")
        while True:
            try:
                if not self._http_client:
                    logger.error("Telegram plugin: HTTP client not available")
                    await asyncio.sleep(5)
                    continue

                resp = await self._http_client.get(
                    f"{self._base_url}/getUpdates",
                    params={
                        "offset": self._offset + 1,
                        "limit": 100,
                        "timeout": 30,  # Long polling timeout
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok"):
                    logger.error(f"Failed to get updates: {data}")
                    await asyncio.sleep(5)
                    continue

                updates = data.get("result", [])
                for update in updates:
                    self._offset = update["update_id"]
                    await self._process_update(update)

                # Sleep briefly if no updates to avoid tight loop
                if not updates:
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logger.info("Telegram polling loop cancelled")
                break
            except Exception as e:
                logger.warning("Error in Telegram polling loop: %s", error_text("telegram_poll_failed", e))
                await asyncio.sleep(5)  # Wait before retrying

    async def _process_update(self, update: dict[str, Any]) -> None:
        # We only care about message updates for now
        if "message" not in update:
            return

        message = update["message"]
        # Extract relevant information
        sender_id = str(message.get("from", {}).get("id"))
        chat_id = str(message.get("chat", {}).get("id"))
        message_id = message.get("message_id")
        date = message.get("date")  # Unix timestamp
        text = message.get("text", "")

        # Build the message dict for the queue
        telegram_message = {
            "sender_id": sender_id,
            "content": text,
            "target": chat_id,  # For Telegram, the target is the chat where the message was sent
            "timestamp": date,
            "raw": update,  # Store the raw update for audit/debugging
            "message_id": message_id,
            "chat_type": message.get("chat", {}).get("type"),  # private, group, supergroup, channel
        }

        # Apply allowlist checks if configured
        if not self._is_sender_allowed(sender_id, telegram_message["chat_type"]):
            logger.debug(f"Telegram message from {sender_id} in chat {chat_id} blocked by allowlist")
            return

        # If we require mention and it's a group/supergroup/channel, check for mention
        if self.require_mention and telegram_message["chat_type"] in ["group", "supergroup", "channel"]:
            # We don't have the bot's username here, but we can check if the message contains the bot's username
            # Alternatively, we can check for entities of type "mention" with the bot's username
            # For simplicity, we'll skip this check in the polling loop and rely on the agent to check mention?
            # But the plugin should filter out non-mentions if require_mention is True.
            # We'll need the bot's username. We can get it during initialization and store it.
            # For now, we'll skip this check and note that it should be implemented.
            # We'll store the bot's username in self._bot_username during initialize.
            pass

        # Put the message in the queue
        await self._message_queue.put(telegram_message)
        logger.debug(f"Telegram message queued from {sender_id} in chat {chat_id}")

    def _is_sender_allowed(self, sender_id: str, chat_type: str) -> bool:
        # If the bot is in a group/supergroup/channel, we might allow all members?
        # But we have the dmPolicy for private chats and groupPolicy for groups?
        # However, our config only has dmPolicy and allowFrom for now.
        # We'll keep it simple:
        #   - For private chats: use dmPolicy and allowFrom
        #   - For groups/channels: we don't have a groupPolicy yet, so we allow all?
        #     But we can extend later.
        if chat_type == "private":
            if self.dm_policy == "disabled":
                return False
            elif self.dm_policy == "open":
                return True
            elif self.dm_policy == "allowlist":
                return sender_id in self.allow_from
            elif self.dm_policy == "pairing":
                # For pairing, we would need to check if the user has been paired via the bot.
                # We don't have pairing storage yet, so we'll treat it as not allowed for now.
                # In a real implementation, we would check a set of paired users.
                return False
            else:
                return False
        else:
            # Groups, channels and supergroups are always allowed; only direct messages have a policy.
            return True
