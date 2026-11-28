"""Microsoft Teams Bot Framework plugin for Octryx."""

import asyncio
import copy
import logging
import time
from typing import Any

import httpx

from ...config import get_settings
from ...services.person_log_ref import person_log_ref
from ..core.base import ChannelPlugin
from .teams_call_lifecycle import (
    _CALLING_MODE_CALL_PROXY,
    _CALLING_MODE_GRAPH_RECORDING,
    _SUPPORTED_CALLING_MODES,
    TeamsCallLifecycle,
)
from .teams_call_media import TeamsCallMedia
from .teams_call_recording import TeamsCallRecording
from .teams_messaging import TeamsMessaging
from .teams_plugin_info import PLUGIN_INFO

logger = logging.getLogger(__name__)

# Bot Framework token endpoint — tenant_id is substituted at runtime
_BF_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_BF_SCOPE = "https://api.botframework.com/.default"


class TeamsPlugin(TeamsMessaging, TeamsCallLifecycle, TeamsCallRecording, TeamsCallMedia, ChannelPlugin):
    """Microsoft Teams Bot Framework channel plugin."""

    def __init__(self, plugin_id: str, config: dict[str, Any]):
        super().__init__(plugin_id, config)
        self.app_id: str = config.get("app_id", "")
        self.app_password: str = config.get("app_password", "")
        self.tenant_id: str = config.get("tenant_id", "botframework.com")
        self.require_mention: bool = config.get("require_mention", True)
        self.thread_followup_policy: str = config.get("thread_followup_policy", "mention_once_per_thread")
        self.dm_policy: str = config.get("dm_policy", "allowlist")
        self.allow_from: list[str] = config.get("allow_from", [])

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

        # Dev mode is only usable when the app itself is running in debug mode.
        self.dev_mode: bool = bool(config.get("dev_mode", False))
        self._dev_mode_active: bool = False

        # Internal state
        self._http_client: httpx.AsyncClient | None = None
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        # Active call sessions: call_id -> {callback_uri, channel_id, project_id, https_base}
        self._active_calls: dict[str, dict] = {}

    # ---------------------------------------------------------------- calling contract

    @property
    def calling_enabled(self) -> bool:
        return bool(self.config.get("calling_enabled", False))

    @property
    def calling_mode(self) -> str:
        mode = str(self.config.get("calling_mode") or _CALLING_MODE_CALL_PROXY).strip().lower()
        if mode not in _SUPPORTED_CALLING_MODES:
            logger.warning("Unsupported Teams calling_mode=%s; using %s", mode, _CALLING_MODE_CALL_PROXY)
            return _CALLING_MODE_CALL_PROXY
        return mode

    @property
    def graph_recording_enabled(self) -> bool:
        return self.calling_enabled and self.calling_mode == _CALLING_MODE_GRAPH_RECORDING

    def _calling_ws_base(self) -> str:
        return str(self.config.get("calling_public_ws_url", "")).strip().rstrip("/")

    def _calling_https_base(self) -> str:
        ws_base = self._calling_ws_base()
        if ws_base.startswith("wss://"):
            return "https://" + ws_base[len("wss://") :]
        if ws_base.startswith("ws://"):
            return "http://" + ws_base[len("ws://") :]
        return ""

    # ------------------------------------------------------------------ token

    async def _ensure_token(self) -> str:
        if self._dev_mode_active:
            logger.debug("Teams dev_mode: using mock access token")
            return "dev-mock-token"

        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        if not self._http_client:
            raise RuntimeError("HTTP client not initialised")

        token_url = _BF_TOKEN_URL_TEMPLATE.format(tenant_id=self.tenant_id)
        resp = await self._http_client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_password,
                "scope": _BF_SCOPE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = time.time() + expires_in
        logger.debug("Teams: fetched new Bot Framework access token")
        return self._access_token

    # Inbound webhook authentication lives in services/channel_webhook_auth.

    # ----------------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        if self.dev_mode:
            settings = get_settings()
            if not settings.debug:
                raise ValueError("Teams dev_mode is only allowed when app debug mode is enabled")
            self._dev_mode_active = True
            self._http_client = httpx.AsyncClient(timeout=30.0)
            logger.warning(
                "Teams plugin started in DEV MODE: the Azure token fetch is disabled. Inbound webhooks "
                "still need a valid Bot Framework token unless OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED "
                "is on. Do NOT use dev_mode in production."
            )
            return

        if not self.app_id or not self.app_password:
            raise ValueError("app_id and app_password are required for Teams plugin")

        self._http_client = httpx.AsyncClient(timeout=30.0)
        try:
            await self._ensure_token()
            logger.info("Teams plugin initialised (credentials verified)")
        except Exception:
            logger.exception("Teams plugin: failed to verify credentials")
            await self._http_client.aclose()
            self._http_client = None
            raise

    async def shutdown(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._access_token = None
        self._dev_mode_active = False
        logger.info("Teams plugin shut down")

    async def _get_graph_token(self) -> str:
        if not self._http_client:
            raise RuntimeError("HTTP client not initialised")
        tenant_id = self.tenant_id if self.tenant_id != "botframework.com" else "common"
        token_url = _BF_TOKEN_URL_TEMPLATE.format(tenant_id=tenant_id)
        resp = await self._http_client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_password,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


        # Recording will start automatically when playPromptOperation completed
        # notification arrives (handled in _handle_graph_calling_notification).


    async def receive_webhook(self, payload: dict) -> dict | None:
        """Called by the webhook endpoint with the raw Bot Framework activity."""
        # Log incoming payload type for debugging the call proxy integration
        odata = payload.get("@odata.type", "")
        act_type = payload.get("type", "")
        logger.info(
            "receive_webhook: @odata.type=%s type=%s keys=%s",
            odata or "(none)",
            act_type or "(none)",
            list(payload.keys())[:10],
        )

        # Microsoft Graph Communications Notifications (calling events)
        if payload.get("@odata.type") == "#microsoft.graph.commsNotifications":
            return await self._handle_graph_calling_notification(payload)

        activity_type = payload.get("type", "")

        if activity_type == "callStateChange":
            value = payload.get("value") or {}
            call_id = str(value.get("id") or payload.get("id") or "")
            state = str(value.get("state") or "")
            logger.info("Teams callStateChange: state=%s call_id=%s", state, call_id)
            if state == "incoming" and call_id:
                return self._build_calling_response(call_id)
            return None

        if activity_type != "message":
            logger.debug("Ignoring Teams activity type=%s name=%s", activity_type, payload.get("name"))
            return None

        text = payload.get("text", "")
        entities = payload.get("entities", [])
        sender = payload.get("from", {})
        sender_id = str(sender.get("id", ""))
        conversation = payload.get("conversation", {})
        conversation_id = str(conversation.get("id", ""))
        service_url = payload.get("serviceUrl", "")
        timestamp = payload.get("timestamp")
        channel_type = conversation.get("conversationType", "")
        bot_mentioned = self._bot_was_mentioned(payload)

        # DM policy check
        if channel_type == "personal":
            if self.dm_policy == "disabled":
                return
            if self.dm_policy == "allowlist" and sender_id not in self.allow_from:
                return
        elif self.require_mention and not bot_mentioned and self.thread_followup_policy != "mention_once_per_thread":
            return

        # Strip <at>BotName</at> mention tags before passing text to the agent
        if entities:
            text = self._strip_mentions(text, entities)

        if not text:
            return

        message = {
            "sender_id": sender_id,
            "content": text,
            "target": f"{service_url}|{conversation_id}",
            "timestamp": timestamp,
            "raw": payload,
            "channel_type": channel_type,
            "conversation_id": conversation_id,
            "bot_mentioned": bot_mentioned,
        }
        await self._message_queue.put(message)
        logger.debug("Teams message queued from %s", person_log_ref(sender_id))

    # ---------------------------------------------------------------- info

    def get_plugin_info(self) -> dict[str, Any]:
        return copy.deepcopy(PLUGIN_INFO)
