"""Matrix homeserver channel plugin for Octryx."""

import asyncio
import logging
import uuid
from typing import Any

import httpx

from app.services.error_facts import error_text

from ..core.base import ChannelPlugin

logger = logging.getLogger(__name__)


class MatrixPlugin(ChannelPlugin):
    """
    Matrix channel plugin.
    Authenticates with username+password or an existing access token,
    then runs a background sync loop to receive messages.
    """

    INBOUND_POLLING = True

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        super().__init__(plugin_id, config)
        self.homeserver: str = config.get("homeserver", "").rstrip("/")
        self.username: str = config.get("username", "")
        self.password: str = config.get("password", "")
        self.access_token: str = config.get("access_token", "")
        self.device_name: str = config.get("device_name", "Octryx")
        self.sync_timeout: int = int(config.get("sync_timeout", 30000))

        # RBAC fields
        self.require_registered_user: bool = config.get("require_registered_user", False)
        self.allowed_roles: list = config.get("allowed_roles", [])
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
        self._sync_task: asyncio.Task | None = None
        self._next_batch: str | None = None
        self._used_password_login: bool = False

    # ------------------------------------------------------------ helpers

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _client_url(self, path: str) -> str:
        return f"{self.homeserver}/_matrix/client/v3{path}"

    # ------------------------------------------------------------ lifecycle

    async def initialize(self) -> None:
        if not self.homeserver:
            raise ValueError("homeserver is required for Matrix plugin")
        if not self.username:
            raise ValueError("username is required for Matrix plugin")

        self._http_client = httpx.AsyncClient(timeout=60.0)

        if self.access_token:
            # Verify the existing access token
            try:
                resp = await self._http_client.get(
                    self._client_url("/account/whoami"),
                    headers=self._headers(),
                )
                resp.raise_for_status()
                logger.info(f"Matrix plugin: using provided access token for {self.username}")
            except Exception:
                logger.exception("Matrix plugin: access_token validation failed")
                await self._http_client.aclose()
                self._http_client = None
                raise
        elif self.password:
            # Login with username + password
            try:
                resp = await self._http_client.post(
                    self._client_url("/login"),
                    json={
                        "type": "m.login.password",
                        "identifier": {"type": "m.id.user", "user": self.username},
                        "password": self.password,
                        "initial_device_display_name": self.device_name,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                self.access_token = data["access_token"]
                self._used_password_login = True
                logger.info(f"Matrix plugin: logged in as {self.username}")
            except Exception:
                logger.exception("Matrix plugin: login failed")
                await self._http_client.aclose()
                self._http_client = None
                raise
        else:
            await self._http_client.aclose()
            self._http_client = None
            raise ValueError("Either password or access_token is required for Matrix plugin")

        # Start background sync loop (only where inbound runs: the background-worker process)
        if not self.inbound_enabled:
            logger.info("Matrix plugin initialized for sending only (inbound sync runs elsewhere)")
            return
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Matrix plugin sync loop started")

    async def shutdown(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.exception(f"Matrix: error stopping sync task: {e}")
            finally:
                self._sync_task = None

        if self._http_client and self._used_password_login and self.access_token:
            try:
                await self._http_client.post(
                    self._client_url("/logout"),
                    headers=self._headers(),
                )
                logger.info("Matrix plugin: logged out")
            except Exception as e:
                logger.warning("Matrix plugin: logout failed: %s", error_text("matrix_logout_failed", e))

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("Matrix plugin shut down")

    # ------------------------------------------------------------ send

    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """
        Send a message to a Matrix room.
        target = room_id (e.g. "!roomid:homeserver")
        """
        if not self._http_client or not self.access_token:
            logger.error("Matrix plugin: not initialised")
            return False

        txn_id = str(uuid.uuid4()).replace("-", "")
        try:
            import urllib.parse

            room_id_encoded = urllib.parse.quote(target, safe="")
            url = self._client_url(f"/rooms/{room_id_encoded}/send/m.room.message/{txn_id}")
            resp = await self._http_client.put(
                url,
                headers=self._headers(),
                json={"msgtype": "m.text", "body": content},
            )
            resp.raise_for_status()
            logger.debug(f"Matrix message sent to room {target}")
            return True
        except Exception as e:
            logger.exception(f"Matrix send_message error for room {target}: {e}")
            return False

    # ---------------------------------------------------------- receive

    async def receive_message(self) -> dict[str, Any] | None:
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # ---------------------------------------------------------- sync loop

    async def _sync_loop(self) -> None:
        """Background task: continuously /sync and queue incoming messages."""
        logger.info("Matrix sync loop running")
        while True:
            try:
                if not self._http_client:
                    await asyncio.sleep(5)
                    continue

                params: dict[str, Any] = {"timeout": self.sync_timeout}
                if self._next_batch:
                    params["since"] = self._next_batch

                resp = await self._http_client.get(
                    self._client_url("/sync"),
                    headers=self._headers(),
                    params=params,
                    timeout=self.sync_timeout / 1000 + 10,
                )
                resp.raise_for_status()
                data = resp.json()

                self._next_batch = data.get("next_batch")
                await self._process_sync(data)

            except asyncio.CancelledError:
                logger.info("Matrix sync loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Matrix sync loop error: {e}")
                await asyncio.sleep(5)

    async def _process_sync(self, data: dict[str, Any]) -> None:
        rooms = data.get("rooms", {})
        join = rooms.get("join", {})
        for room_id, room_data in join.items():
            timeline = room_data.get("timeline", {})
            events = timeline.get("events", [])
            for event in events:
                if event.get("type") != "m.room.message":
                    continue
                content = event.get("content", {})
                if content.get("msgtype") != "m.text":
                    continue
                sender = event.get("sender", "")
                body = content.get("body", "")
                origin_server_ts = event.get("origin_server_ts", 0)
                msg = {
                    "sender_id": sender,
                    "content": body,
                    "target": room_id,
                    "timestamp": origin_server_ts,
                    "raw": event,
                }
                await self._message_queue.put(msg)
                logger.debug(f"Matrix message queued from {sender} in {room_id}")

    # -------------------------------------------------------- info

    def get_plugin_info(self) -> dict[str, Any]:
        return {
            "id": "matrix",
            "name": "Matrix",
            "description": "Matrix homeserver channel plugin for sending and receiving messages",
            "version": "0.1.0",
            "author": "Octryx",
            "config_fields": [
                {
                    "name": "homeserver",
                    "type": "string",
                    "required": True,
                    "description": "Matrix homeserver URL (e.g. https://matrix.org)",
                },
                {
                    "name": "username",
                    "type": "string",
                    "required": True,
                    "description": "Matrix username (e.g. @user:matrix.org)",
                },
                {
                    "name": "password",
                    "type": "string",
                    "secret": True,
                    "description": "Matrix account password (used if access_token is not provided)",
                },
                {
                    "name": "access_token",
                    "type": "string",
                    "secret": True,
                    "description": "Matrix access token (alternative to password login)",
                },
                {
                    "name": "device_name",
                    "type": "string",
                    "default": "Octryx",
                    "description": "Display name for this session/device",
                },
                {
                    "name": "sync_timeout",
                    "type": "number",
                    "default": 30000,
                    "description": "Long-poll timeout for /sync in milliseconds",
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
                    "description": 'JSON object mapping external sender IDs to platform user IDs, e.g. {"@user:matrix.org": "user-uuid"}',
                },
                {
                    "name": "allowed_roles",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated role names allowed to use this channel (empty = all roles)",
                },
            ],
        }
