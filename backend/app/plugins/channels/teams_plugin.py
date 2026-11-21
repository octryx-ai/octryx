"""Microsoft Teams Bot Framework plugin for Octryx."""

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from ...config import get_settings
from ...services.person_log_ref import person_log_ref
from ..core.base import ChannelPlugin

logger = logging.getLogger(__name__)

# Bot Framework token endpoint — tenant_id is substituted at runtime
_BF_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_BF_SCOPE = "https://api.botframework.com/.default"

_CALLING_MODE_CALL_PROXY = "call_proxy"  # an external call proxy answers the call and streams its audio
_CALLING_MODE_GRAPH_RECORDING = "graph_recording"
_SUPPORTED_CALLING_MODES = {_CALLING_MODE_CALL_PROXY, _CALLING_MODE_GRAPH_RECORDING}


class TeamsPlugin(ChannelPlugin):
    """
    Microsoft Teams Bot Framework channel plugin.
    Receives activities via webhook; sends via Bot Framework Connector API.
    """

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
        """Return a valid Bot Framework access token, fetching a new one if needed."""
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

    # ------------------------------------------------------------------ send

    async def send_message(self, target: str, content: str, **kwargs) -> bool:
        """
        Send a message to Teams.

        Supported target formats:
        - "{serviceUrl}|{conversationId}" posts to an existing conversation.
        - "thread|{serviceUrl}|{tenantId}|{teamId}|{channelId}" creates a new
          channel thread for this delivery.
        """
        if not self._http_client:
            logger.error("Teams plugin: not initialised")
            return False

        try:
            token = await self._ensure_token()
            if target.startswith("thread|"):
                return await self._create_channel_thread(target, content, token)
            return await self._send_existing_conversation_message(target, content, token)
        except Exception as e:
            logger.exception("Teams send_message error: %s", e)
            return False

    async def _send_existing_conversation_message(self, target: str, content: str, token: str) -> bool:
        parts = target.split("|", 1)
        if len(parts) != 2:
            logger.error(
                "Teams send_message: target must be 'serviceUrl|conversationId' or "
                "'thread|serviceUrl|tenantId|teamId|channelId'"
            )
            return False
        service_url, conversation_id = parts
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        assert self._http_client is not None
        resp = await self._http_client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "message", "text": content},
        )
        resp.raise_for_status()
        logger.debug("Teams message sent to conversation %s", conversation_id)
        return True

    async def _create_channel_thread(self, target: str, content: str, token: str) -> bool:
        parts = target.split("|")
        if len(parts) != 5:
            logger.error("Teams thread target must be 'thread|serviceUrl|tenantId|teamId|channelId'")
            return False
        _, service_url, tenant_id, team_id, channel_id = parts
        if not all((service_url, tenant_id, team_id, channel_id)):
            logger.error("Teams thread target contains empty serviceUrl, tenantId, teamId, or channelId")
            return False

        url = f"{service_url.rstrip('/')}/v3/conversations"
        bot_name = str(self.config.get("__channel_name") or self.config.get("name") or "Octryx")
        payload = {
            "isGroup": True,
            "bot": {"id": self.app_id, "name": bot_name},
            "activity": {"type": "message", "text": content},
            "channelData": {
                "tenant": {"id": tenant_id},
                "team": {"id": team_id},
                "channel": {"id": channel_id},
                "teamsTeamId": team_id,
                "teamsChannelId": channel_id,
            },
        }
        assert self._http_client is not None
        resp = await self._http_client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        logger.debug("Teams channel thread created for team %s channel %s", team_id, channel_id)
        return True

    # ----------------------------------------------------------------- receive

    async def receive_message(self) -> dict[str, Any] | None:
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @staticmethod
    def _strip_mentions(text: str, entities: list[dict]) -> str:
        """Remove all <at>...</at> mention tags from text."""
        import re as _re

        for entity in entities:
            if entity.get("type") == "mention":
                mention_text = entity.get("text", "")
                if mention_text:
                    text = text.replace(mention_text, "")
        # Catch any remaining <at>...</at> tags
        text = _re.sub(r"<at>[^<]*</at>", "", text)
        return text.strip()

    def _bot_was_mentioned(self, payload: dict) -> bool:
        """Return True if the bot's own ID appears in the entities mention list."""
        bot_id = payload.get("recipient", {}).get("id", "")
        for entity in payload.get("entities", []):
            if entity.get("type") == "mention":
                if entity.get("mentioned", {}).get("id") == bot_id:
                    return True
        return False

    def _build_calling_response(self, call_id: str) -> dict | None:
        """Return the audio WebSocket URI for the call proxy to stream PCM to."""
        if not self.calling_enabled:
            logger.info("Teams calling disabled — ignoring incoming call %s", call_id)
            return None
        if self.calling_mode != _CALLING_MODE_CALL_PROXY:
            logger.info("Teams calling mode %s does not use audioWebSocketUri responses", self.calling_mode)
            return None
        ws_base = self._calling_ws_base()
        if not ws_base.startswith(("wss://", "ws://")):
            logger.warning("calling_public_ws_url must start with ws:// or wss:// — cannot answer call %s", call_id)
            return None
        if not ws_base:
            logger.warning("calling_public_ws_url not configured — cannot answer call %s", call_id)
            return None
        channel_id = str(self.config.get("__channel_id", ""))
        project_id = str(self.config.get("__channel_project_id", ""))
        if not channel_id or not project_id:
            logger.warning("Teams calling requires channel and project binding — cannot answer call %s", call_id)
            return None
        from ...services.teams_calling.audio_ws_token import issue_call_audio_token

        # The per-call, single-use token the audio WebSocket requires; never logged.
        audio_token = issue_call_audio_token(call_id, channel_id=channel_id)
        query = urlencode({"project_id": project_id, "channel_id": channel_id, "token": audio_token})
        audio_ws_url = f"{ws_base}/api/v1/teams/calls/{quote(call_id, safe='')}/audio/ws?{query}"
        logger.info("Answering call %s via the call proxy with a per-call audio WS token", call_id)
        return {"audioWebSocketUri": audio_ws_url}

    def _https_base(self) -> str:
        return self._calling_https_base()

    def _callback_uri(self) -> str:
        return f"{self._https_base()}/api/v1/channels/{self.config.get('__channel_id', '')}/webhook"

    async def _get_graph_token(self) -> str:
        """Get a Microsoft Graph access token (Communications scope)."""
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

    async def _redirect_to_call_proxy(self, call_id: str) -> None:
        """Redirect an incoming (not yet answered) call to the call proxy for streaming.

        The call proxy handles the media and connects to our WebSocket endpoint
        for bidirectional audio streaming. This eliminates the beep from recordResponse.

        Flow:
        1. We redirect the ringing call to the call proxy
        2. The call proxy answers and handles media
        3. The call proxy calls our /incoming-call endpoint to get the WS URL
        4. Audio streams bidirectionally over WebSocket
        """
        try:
            token = await self._get_graph_token()
            call_info = self._active_calls.get(call_id, {})
            channel_id = call_info.get("channel_id", "")
            project_id = call_info.get("project_id", "")
            https_base = call_info.get("https_base", "")

            # The call proxy's webhook URL from channel config
            vbc_url = str(self.config.get("calling_webhook_url") or "").strip()
            if not vbc_url:
                logger.warning(
                    "No calling_webhook_url configured — falling back to graph_recording for call %s", call_id
                )
                await self._answer_graph_call(call_id)
                return

            from ...services.teams_calling.audio_ws_token import issue_call_audio_token

            # Build our callback URL that the call proxy will use to get audio WS details; it
            # carries the call's audio WS token, which /incoming-call only passes through.
            audio_token = issue_call_audio_token(call_id, channel_id=str(channel_id))
            callback_url = f"{https_base}/api/v1/teams/calls/incoming-call?" + urlencode(
                {"call_id": call_id, "channel_id": channel_id, "project_id": project_id, "audio_token": audio_token}
            )

            # Redirect the call to the call proxy
            # Graph API: POST /communications/calls/{id}/redirect
            body = {
                "targets": [
                    {
                        "@odata.type": "#microsoft.graph.invitationParticipantInfo",
                        "identity": {
                            "@odata.type": "#microsoft.graph.identitySet",
                            "application": {
                                "@odata.type": "#microsoft.graph.identity",
                                "id": self.app_id,
                                "displayName": "VirtualWorker",
                            },
                        },
                    }
                ],
                "callbackUri": callback_url,
            }

            logger.info("Redirecting call %s to the call proxy", call_id)

            resp = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/redirect",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )

            if resp.status_code in (200, 202, 204):
                logger.info("Call %s redirected to the call proxy successfully", call_id)
            else:
                logger.warning(
                    "Redirect failed for call %s (HTTP %s, body_chars=%d) — falling back to graph_recording",
                    call_id,
                    resp.status_code,
                    len(resp.text or ""),
                )
                # Fallback: answer the call ourselves with recordResponse
                await self._answer_graph_call(call_id)

        except Exception:
            logger.exception("Failed to redirect call %s to the call proxy — falling back to graph_recording", call_id)
            await self._answer_graph_call(call_id)

    async def _answer_graph_call(self, call_id: str) -> None:
        """Answer an incoming call via Microsoft Graph Communications API."""
        try:
            token = await self._get_graph_token()
            callback_uri = self._callback_uri()
            body = {
                "callbackUri": callback_uri,
                "acceptedModalities": ["audio"],
                "mediaConfig": {
                    "@odata.type": "#microsoft.graph.serviceHostedMediaConfig",
                },
            }
            resp = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/answer",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            logger.info("Graph answer call %s → HTTP %s", call_id, resp.status_code)
            if resp.status_code not in (200, 202, 204):
                logger.warning("Graph answer failed: HTTP %s body_chars=%d", resp.status_code, len(resp.text or ""))
        except Exception:
            logger.exception("Failed to answer call %s via Graph API", call_id)

    async def _cancel_media_processing(self, call_id: str) -> None:
        """Cancel any currently playing audio (barge-in) via Graph API cancelMediaProcessing."""
        try:
            import uuid as _uuid

            token = await self._get_graph_token()
            body = {"clientContext": str(_uuid.uuid4())}
            resp = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/cancelMediaProcessing",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            logger.info("cancelMediaProcessing %s → HTTP %s", call_id, resp.status_code)
        except Exception:
            logger.debug("cancelMediaProcessing failed for %s (non-critical)", call_id)

    async def _play_prompt(self, call_id: str, audio_url: str) -> None:
        """Play an audio URL in the call via Graph API playPrompt."""
        import uuid as _uuid

        try:
            token = await self._get_graph_token()
            body = {
                "clientContext": str(_uuid.uuid4()),
                "prompts": [
                    {
                        "@odata.type": "#microsoft.graph.mediaPrompt",
                        "mediaInfo": {
                            "@odata.type": "#microsoft.graph.mediaInfo",
                            "uri": audio_url,
                            "resourceId": str(_uuid.uuid4()),
                        },
                    }
                ],
                "loop": False,
            }
            resp = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/playPrompt",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            logger.info("playPrompt %s → HTTP %s body_chars=%d", call_id, resp.status_code, len(resp.text or ""))
        except Exception:
            logger.exception("playPrompt failed for call %s", call_id)

    async def _fetch_caller_display_name(self, call_id: str) -> None:
        """Fetch the caller's display name via Graph API GET /communications/calls/{id}/participants.

        Graph commsNotifications don't include displayName in the identity object,
        so we must query it separately after the call is established.
        """
        import sys as _sys

        call_info = self._active_calls.get(call_id)
        if not call_info:
            return
        try:
            token = await self._get_graph_token()
            resp = await self._http_client.get(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/participants",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                participants = data.get("value") or []
                for participant in participants:
                    info = participant.get("info") or {}
                    identity_set = info.get("identity") or {}
                    user = identity_set.get("user") or {}
                    display_name = str(user.get("displayName") or "").strip()
                    user_id = str(user.get("id") or "").strip()

                    # Skip the bot itself (match by app_id)
                    app = identity_set.get("application") or {}
                    if app.get("id") == self.app_id:
                        continue

                    if display_name:
                        call_info["caller_display_name"] = display_name
                        if not call_info.get("caller_id"):
                            call_info["caller_id"] = user_id
                        print(
                            f"[NOTIF CALLER DEBUG] Fetched caller name via API: caller={person_log_ref(display_name)} (id={person_log_ref(user_id)})",
                            file=_sys.stderr,
                            flush=True,
                        )
                        logger.info(
                            "Call %s: caller identified as %s via participants API", call_id, person_log_ref(display_name)
                        )
                        return

                # If no user participant found, log what we got
                print(
                    f"[NOTIF CALLER DEBUG] Participants API returned {len(participants)} participants, no displayName found",
                    file=_sys.stderr,
                    flush=True,
                )
            else:
                print(
                    f"[NOTIF CALLER DEBUG] Participants API HTTP {resp.status_code}",
                    file=_sys.stderr,
                    flush=True,
                )
        except Exception as _err:
            print(
                f"[NOTIF CALLER DEBUG] Participants API failed: error_type={type(_err).__name__}",
                file=_sys.stderr,
                flush=True,
            )
            logger.debug("Failed to fetch participants for call %s: %s", call_id, type(_err).__name__)

    async def _play_greeting_then_record(self, call_id: str) -> None:
        """Play a TTS greeting and start recording in parallel for barge-in support.

        Uses the configurable `call_greeting_template` from channel config.
        The template can contain {first_name} and {full_name} placeholders.
        Default: "Hi {first_name}, I'm listening. How can I assist you?"

        Recording starts immediately alongside the greeting so the caller's
        speech is captured even if they speak during/right after the greeting
        (barge-in support).
        """
        import sys as _sys
        import uuid as _uuid

        call_info = self._active_calls.get(call_id, {})
        https_base = call_info.get("https_base", "")

        if not https_base:
            logger.warning("No https_base for call %s — falling back to _start_record directly", call_id)
            await self._start_record(call_id)
            return

        # Resolve greeting template from channel config
        greeting_template = (
            str(self.config.get("call_greeting_template", "")).strip()
            or "Hi {first_name}, I'm listening. How can I assist you?"
        )

        # Resolve caller name placeholders
        full_name = call_info.get("caller_display_name", "").strip()
        first_name = full_name.split()[0] if full_name else "there"
        greeting_text = greeting_template.replace("{first_name}", first_name).replace(
            "{full_name}", full_name or "there"
        )

        print(
            f"[CALL DEBUG] Greeting for {call_id}: chars={len(greeting_text)} (caller={person_log_ref(full_name)})",
            file=_sys.stderr,
            flush=True,
        )
        logger.info("Call %s: generating TTS greeting: chars=%d", call_id, len(greeting_text))

        # Try TTS synthesis for the greeting
        greeting_audio = None
        try:
            from ...db import async_session_factory
            from ...services.tts import get_tts_provider

            async with async_session_factory() as db:
                # The channel's Workspace voice settings apply, not only the platform ones.
                project_id = str(call_info.get("project_id") or self.config.get("__channel_project_id", "")) or None
                provider = await get_tts_provider(db, project_id=project_id)
                if provider:
                    greeting_audio = await provider.synthesize(greeting_text, voice="alloy", speed=1.0)
                    print(f"[CALL DEBUG] Greeting TTS OK: {len(greeting_audio)} bytes", file=_sys.stderr, flush=True)
        except Exception as _tts_err:
            print(
                f"[CALL DEBUG] Greeting TTS failed: error_type={type(_tts_err).__name__}", file=_sys.stderr, flush=True
            )
            logger.warning("Greeting TTS failed for call %s: %s", call_id, type(_tts_err).__name__)

        # Fallback to silent WAV if TTS fails
        if not greeting_audio:
            greeting_audio = self._generate_greeting_wav()

        # Store as temp audio and build a publicly accessible URL
        from ...services.teams_calling.call_session_state import _temp_audio

        file_id = str(_uuid.uuid4())
        _temp_audio[file_id] = greeting_audio
        audio_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"

        logger.info("Call %s: playing greeting at %s", call_id, audio_url)
        await self._play_prompt(call_id, audio_url)
        # Recording will start automatically when playPromptOperation completed
        # notification arrives (handled in _handle_graph_calling_notification).

    @staticmethod
    def _generate_greeting_wav() -> bytes:
        """Generate a short silent WAV file for media pipeline warmup.

        Produces ~0.3s of silence at 16kHz/16bit/mono wrapped in WAV.
        The silence is enough to activate Graph's media pipeline without
        producing any audible sound for the caller.
        """
        import io
        import wave

        sample_rate = 16000
        duration_s = 0.3

        num_samples = int(sample_rate * duration_s)
        # Pure silence: all zero samples
        pcm_data = b"\x00\x00" * num_samples

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return buf.getvalue()

    # Track which calls currently have an active recordResponse in-flight.
    # Prevents multiple simultaneous recordings (Graph only supports one at a time).
    _recording_active: dict[str, bool] = {}

    async def _start_record(
        self,
        call_id: str,
        *,
        max_duration: int | None = None,
        initial_silence: int | None = None,
        max_silence: int | None = None,
        play_beep: bool = False,
    ) -> None:
        """Start recording the caller's speech via Graph API.

        Uses playBeep=False and an explicit empty prompts list to suppress any
        audible beep on serviceHostedMediaConfig calls.

        Guards against concurrent recordings: if a recording is already marked
        as active for this call, this method is a no-op.

        Args:
            call_id: The Graph call ID
            max_duration: Override maxRecordDurationInSeconds (default: 10)
            initial_silence: Override initialSilenceTimeoutInSeconds (default: 5)
            max_silence: Override maxSilenceTimeoutInSeconds (default: 3)
            play_beep: Whether to play the Graph built-in beep (default: False)
        """
        # Guard: only one recording at a time per call
        if self._recording_active.get(call_id):
            logger.info("_start_record(%s): skipped — recording already active", call_id)
            return
        self._recording_active[call_id] = True

        import uuid as _uuid

        try:
            token = await self._get_graph_token()

            # First: subscribe to tone events so Graph enables the audio receive path
            try:
                subscribe_body = {
                    "clientContext": str(_uuid.uuid4()),
                }
                await self._http_client.post(
                    f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/subscribeToTone",
                    json=subscribe_body,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
            except Exception:
                logger.debug("subscribeToTone failed for %s (non-critical)", call_id)

            # Build a silent prompt URI from the greeting WAV to override Graph's built-in beep
            call_info = self._active_calls.get(call_id, {})
            https_base = call_info.get("https_base", "")

            body = {
                "bargeInAllowed": True,
                "clientContext": str(_uuid.uuid4()),
                "maxRecordDurationInSeconds": max_duration or 10,
                "initialSilenceTimeoutInSeconds": initial_silence or 5,
                "maxSilenceTimeoutInSeconds": max_silence or 3,
                "stopTones": ["#"],
                "playBeep": play_beep,
            }

            # Provide an explicit silent prompt to suppress Graph's default beep.
            # Graph ignores playBeep=False on serviceHostedMediaConfig unless prompts is set.
            if https_base:
                from ...services.teams_calling.call_session_state import _temp_audio

                silence_wav = self._generate_greeting_wav()
                file_id = str(_uuid.uuid4())
                _temp_audio[file_id] = silence_wav
                silence_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"
                body["prompts"] = [
                    {
                        "@odata.type": "#microsoft.graph.mediaPrompt",
                        "mediaInfo": {
                            "@odata.type": "#microsoft.graph.mediaInfo",
                            "uri": silence_url,
                            "resourceId": str(_uuid.uuid4()),
                        },
                    }
                ]

            resp = await self._http_client.post(
                f"https://graph.microsoft.com/v1.0/communications/calls/{call_id}/recordResponse",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            logger.warning(
                "recordResponse %s -> HTTP %s body_chars=%d", call_id, resp.status_code, len(resp.text or "")
            )
            if resp.status_code >= 400:
                # Request rejected — clear the active flag immediately
                self._recording_active.pop(call_id, None)
        except Exception:
            logger.exception("recordResponse failed for call %s", call_id)
            self._recording_active.pop(call_id, None)

    @staticmethod
    def _extract_call_id(resource: str) -> str:
        """Extract call ID from Graph resource paths like /communications/calls/{id} or /communications/calls/{id}/operations/{opId}."""
        parts = resource.strip("/").split("/")
        try:
            idx = parts.index("calls")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except ValueError:
            pass
        return resource.rstrip("/").split("/")[-1]

    async def _handle_graph_calling_notification(self, payload: dict) -> dict:
        """Handle Microsoft Graph Communications Notifications (calling events)."""
        if not self.calling_enabled:
            logger.info("Ignoring Graph calling notification because Teams calling is disabled")
            return {"status": "ignored", "reason": "calling_disabled"}
        import asyncio as _asyncio

        notifications = payload.get("value") or []
        for notif in notifications:
            change_type = str(notif.get("changeType") or "")
            resource_data = notif.get("resourceData") or {}
            resource = str(notif.get("resourceUrl") or notif.get("resource") or "")
            odata_type = str(resource_data.get("@odata.type") or "")
            call_id = self._extract_call_id(resource)

            logger.info(
                "Graph notification: changeType=%s odata=%s state=%s call_id=%s",
                change_type,
                odata_type,
                resource_data.get("state", ""),
                call_id,
            )

            if not call_id:
                continue

            # DEBUG: print every notification for troubleshooting
            import sys as _sys

            print(
                f"[NOTIF DETAIL] call_id={call_id} changeType={change_type} odata={odata_type} state={resource_data.get('state', '')} status={resource_data.get('status', '')} active_calls={list(self._active_calls.keys())[:3]}",
                file=_sys.stderr,
                flush=True,
            )
            # Incoming calls log only the resourceData keys; the provider payload itself is never logged.
            if resource_data.get("state") == "incoming":
                print(f"[NOTIF INCOMING FULL] keys={list(resource_data.keys())}", file=_sys.stderr, flush=True)

            # Incoming call → store state and answer (or redirect to the call proxy for streaming)
            if change_type == "created" and resource_data.get("state") == "incoming":
                # Extract caller identity from Graph notification
                # Graph may put caller info in "source", "incomingContext", or top-level fields
                source = resource_data.get("source") or {}
                caller_identity = source.get("identity") or {}
                caller_user = caller_identity.get("user") or {}
                caller_display_name = str(caller_user.get("displayName") or "").strip()
                caller_id = str(caller_user.get("id") or "").strip()

                # Fallback: try incomingContext.observedParticipantId or other paths
                if not caller_display_name:
                    incoming_ctx = resource_data.get("incomingContext") or {}
                    if not caller_id:
                        caller_id = str(incoming_ctx.get("sourceParticipantId") or "").strip()
                    if not caller_display_name:
                        # Try the notification-level source
                        notif_source = notif.get("resourceData", {}).get("source") or {}
                        caller_display_name = str(
                            notif_source.get("identity", {}).get("user", {}).get("displayName") or ""
                        ).strip()

                # DEBUG: Log full resourceData keys to find where caller name lives
                print(
                    f"[NOTIF CALLER DEBUG] call_id={call_id} resourceData keys={list(resource_data.keys())} caller={person_log_ref(caller_display_name)}",
                    file=_sys.stderr,
                    flush=True,
                )

                # Determine if this is a 1:1 direct call (not a group/meeting)
                # Graph signals group calls via meetingInfo or participants count
                meeting_info = resource_data.get("meetingInfo")
                is_direct_call = meeting_info is None

                if caller_display_name:
                    logger.info(
                        "Incoming call %s from %s (id=%s, direct=%s)",
                        call_id,
                        person_log_ref(caller_display_name),
                        person_log_ref(caller_id),
                        is_direct_call,
                    )

                self._active_calls[call_id] = {
                    "channel_id": str(self.config.get("__channel_id", "")),
                    "project_id": str(self.config.get("__channel_project_id", "")),
                    "https_base": self._https_base(),
                    "caller_display_name": caller_display_name,
                    "caller_id": caller_id,
                    "is_direct_call": is_direct_call,
                }
                if self.calling_mode == _CALLING_MODE_CALL_PROXY:
                    # Streaming mode: return audioWebSocketUri directly in the HTTP
                    # response so the call proxy knows where to stream audio.
                    resp = self._build_calling_response(call_id)
                    if resp:
                        logger.info("Returning audioWebSocketUri to the call proxy for call %s", call_id)
                        return resp
                    logger.warning(
                        "Could not build audioWebSocketUri for call %s — Graph recording fallback is disabled",
                        call_id,
                    )
                    self._active_calls.pop(call_id, None)
                    return {"status": "ignored", "reason": "graph_recording_disabled"}
                else:
                    # graph_recording mode: answer and use recordResponse
                    _asyncio.create_task(self._answer_graph_call(call_id))

            # Call established → fetch caller name, then play TTS greeting + start recording
            elif resource_data.get("state") == "established" and call_id in self._active_calls:
                call_info = self._active_calls[call_id]

                if not call_info.get("recording_started"):
                    call_info["recording_started"] = True
                    if self.calling_mode == _CALLING_MODE_GRAPH_RECORDING:
                        logger.info("Call %s established — fetching caller name then playing greeting", call_id)

                        async def _greet_with_name(cid: str):
                            """Fetch caller name (if needed) then play greeting."""
                            ci = self._active_calls.get(cid, {})
                            if not ci.get("caller_display_name"):
                                await self._fetch_caller_display_name(cid)
                            await self._play_greeting_then_record(cid)

                        _asyncio.create_task(_greet_with_name(call_id))
                    else:
                        # Still fetch name for later use
                        if not call_info.get("caller_display_name"):
                            _asyncio.create_task(self._fetch_caller_display_name(call_id))
                        logger.info("Call %s established in call_proxy mode — waiting for audio stream", call_id)

            # Recording completed → hand off to processing worker
            elif odata_type == "#microsoft.graph.recordOperation" and resource_data.get("status") == "completed":
                # Clear recording-active guard — this recording has finished
                self._recording_active.pop(call_id, None)

                recording_location = str(resource_data.get("recordingLocation") or "")
                recording_access_token = str(resource_data.get("recordingAccessToken") or "")
                completion_reason = str(resource_data.get("completionReason") or "")
                logger.info(
                    "Recording completed for call %s (reason=%s): %s",
                    call_id,
                    completion_reason,
                    recording_location[:80] if recording_location else "no URL",
                )

                # If the bot is currently speaking, suppress recording restart.
                # Graph does not allow recordResponse during playPrompt anyway.
                from ...services.teams_calling.call_session_state import is_bot_speaking as _bot_speaking_check

                if _bot_speaking_check(call_id):
                    logger.info("Recording completed for call %s while bot is speaking — suppressing", call_id)
                elif recording_location and call_id in self._active_calls:
                    call_info = self._active_calls[call_id]
                    try:
                        from ...services.teams_calling.recording_processor import enqueue_recording

                        enqueue_recording(
                            {
                                "call_id": call_id,
                                "recording_location": recording_location,
                                "recording_access_token": recording_access_token,
                                "channel_id": call_info["channel_id"],
                                "project_id": call_info["project_id"],
                                "https_base": call_info["https_base"],
                                "caller_display_name": call_info.get("caller_display_name", ""),
                                "caller_id": call_info.get("caller_id", ""),
                                "is_direct_call": call_info.get("is_direct_call", False),
                                "completion_reason": completion_reason,
                            }
                        )
                        # Do NOT restart recording here — the worker will restart
                        # recording after the bot finishes speaking (sequential flow).
                        logger.info(
                            "Recording enqueued for %s — waiting for worker to restart recording after response",
                            call_id,
                        )
                    except Exception:
                        logger.exception("Failed to enqueue recording for call %s", call_id)
                        _asyncio.create_task(self._start_record(call_id))
                elif not recording_location:
                    logger.warning(
                        "recordOperation completed but no recordingLocation for call %s (reason=%s)",
                        call_id,
                        completion_reason,
                    )
                    if call_id in self._active_calls:
                        # On silence timeout, restart recording with a small delay
                        if completion_reason in ("maxSilenceReached", "mediaReceiveTimedOut", "initialSilenceTimedOut"):

                            async def _delayed_restart(cid: str):
                                await _asyncio.sleep(1.0)
                                if cid in self._active_calls:
                                    await self._start_record(cid)

                            _asyncio.create_task(_delayed_restart(call_id))
                        else:
                            _asyncio.create_task(self._start_record(call_id))

            # Play prompt completed → start next recording cycle
            elif odata_type == "#microsoft.graph.playPromptOperation" and resource_data.get("status") == "completed":
                # DON'T auto-restart recording during enrollment or while bot is speaking.
                # The response handler manages its own recording timing after playback.
                from ...services.teams_calling.call_session_state import is_bot_speaking, signal_playback_done
                from ...services.teams_calling.enrollment_flow import is_enrollment_active

                if is_enrollment_active(call_id):
                    logger.info(
                        "playPrompt completed for call %s — enrollment active, NOT restarting recording", call_id
                    )
                elif is_bot_speaking(call_id):
                    # Signal the worker that playback is done — it will handle recording restart
                    logger.info("playPrompt completed for call %s — signaling worker (bot response done)", call_id)
                    signal_playback_done(call_id)
                else:
                    logger.info("playPrompt completed for call %s — starting recording", call_id)
                    if call_id in self._active_calls:
                        _asyncio.create_task(self._start_record(call_id))

            # Recording failed/cancelled → restart (but NOT if bot is speaking — playPrompt cancels recordings)
            elif odata_type == "#microsoft.graph.recordOperation" and resource_data.get("status") in (
                "failed",
                "cancelled",
            ):
                # Clear recording-active guard — this recording is done
                self._recording_active.pop(call_id, None)

                from ...services.teams_calling.call_session_state import is_bot_speaking as _bot_speaking_fail_check

                if _bot_speaking_fail_check(call_id):
                    logger.info(
                        "Recording %s for call %s while bot is speaking — NOT restarting (playPrompt handler will restart)",
                        resource_data.get("status"),
                        call_id,
                    )
                elif call_id in self._active_calls:
                    logger.warning("Recording %s for call %s — restarting", resource_data.get("status"), call_id)
                    _asyncio.create_task(self._start_record(call_id))

            # Call terminated → cleanup
            elif resource_data.get("state") == "terminated":
                self._active_calls.pop(call_id, None)
                self._recording_active.pop(call_id, None)
                logger.info("Call %s terminated — cleaned up", call_id)
                try:
                    from ...services.teams_calling.call_session_state import close_call_db_session

                    _asyncio.create_task(close_call_db_session(call_id))
                except Exception:
                    logger.exception("Failed to close call DB session for %s", call_id)

        return {"status": "accepted"}

    async def receive_webhook(self, payload: dict) -> dict | None:
        """
        Called by the webhook endpoint with the raw Bot Framework activity.
        Validates the activity and queues it as a message.
        Returns a response dict for calling activities, None for message activities.
        """
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
        return {
            "id": "msteams",
            "name": "Microsoft Teams",
            "description": "Microsoft Teams Bot Framework channel plugin for sending and receiving messages",
            "version": "0.1.0",
            "author": "Octryx",
            "config_fields": [
                {
                    "name": "app_id",
                    "type": "string",
                    "required": True,
                    "description": "Azure Bot App ID (Application / Client ID)",
                },
                {
                    "name": "app_password",
                    "type": "string",
                    "secret": True,
                    "required": True,
                    "description": "Azure Bot App Password (Client Secret)",
                },
                {
                    "name": "tenant_id",
                    "type": "string",
                    "default": "botframework.com",
                    "description": "Azure AD tenant ID (use 'botframework.com' for multi-tenant bots)",
                },
                {
                    "name": "require_mention",
                    "type": "boolean",
                    "default": True,
                    "description": "Only respond to messages that @mention the bot in group chats",
                },
                {
                    "name": "thread_followup_policy",
                    "type": "select",
                    "options": ["mention_every_message", "mention_once_per_thread"],
                    "default": "mention_once_per_thread",
                    "description": "Allow follow-up messages in an already activated Teams thread without @mention",
                },
                {
                    "name": "dm_policy",
                    "type": "select",
                    "options": ["open", "allowlist", "disabled"],
                    "default": "allowlist",
                    "description": "Policy for direct messages (personal conversations)",
                },
                {
                    "name": "allow_from",
                    "type": "list",
                    "default": [],
                    "description": "Allowed sender IDs for DMs when dm_policy is 'allowlist'",
                },
                {
                    "name": "default_target",
                    "type": "string",
                    "default": "",
                    "description": (
                        "Default proactive target formatted as serviceUrl|conversationId for task output delivery"
                    ),
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
                    "description": (
                        'JSON object mapping external sender IDs to platform user IDs, e.g. {"123": "user-uuid"}'
                    ),
                },
                {
                    "name": "allowed_roles",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated role names allowed to use this channel (empty = all roles)",
                },
                {
                    "name": "dev_mode",
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Skip the Azure token fetch (debug/local development only; blocked unless app "
                        "debug mode is enabled). Inbound webhooks are still authenticated."
                    ),
                },
                {
                    "name": "calling_enabled",
                    "type": "boolean",
                    "default": False,
                    "description": "Enable voice calling (Teams Calling / CallAgent)",
                },
                {
                    "name": "calling_mode",
                    "type": "select",
                    "options": ["call_proxy", "graph_recording"],
                    "default": "call_proxy",
                    "description": (
                        "Calling integration mode. call_proxy returns audioWebSocketUri for invited calls; "
                        "graph_recording is experimental and requires Microsoft Graph communications permissions."
                    ),
                },
                {
                    "name": "calling_public_ws_url",
                    "type": "string",
                    "default": "",
                    "description": "Public WebSocket URL for MediaBridge to connect (local dev: ngrok URL, e.g. wss://xxx.ngrok-free.dev; EKS: public cluster domain)",
                },
                {
                    "name": "calling_webhook_url",
                    "type": "string",
                    "default": "",
                    "description": "Teams Calling webhook URL: the call proxy's incoming-call endpoint (e.g. https://<call-proxy-host>/<incoming-call-path>)",
                },
                {
                    "name": "call_agent_thinking_message",
                    "type": "string",
                    "default": "One moment please, I'm looking into this.",
                    "description": "Message played to the caller while the agent is processing.",
                },
                {
                    "name": "call_require_wake_word",
                    "type": "boolean",
                    "default": True,
                    "description": "Only respond when a configured wake word is present in the transcribed speech.",
                },
                {
                    "name": "call_wake_words",
                    "type": "string",
                    "default": "hey octryx,octryx",
                    "description": "Comma-separated wake words for Teams calls.",
                },
                {
                    "name": "call_agent_max_tool_calls",
                    "type": "number",
                    "default": 5,
                    "description": "Maximum number of tool calls the CallAgent can make per turn.",
                },
                {
                    "name": "call_agent_system_prompt",
                    "type": "string",
                    "default": "You are a helpful meeting assistant. You help with status checks, questions about projects, and decisions. You can use tools to fetch information. Answer concisely and clearly, in the language the caller uses.",
                    "description": "System prompt for the CallAgent voice assistant.",
                },
                {
                    "name": "call_agent_llm_model",
                    "type": "string",
                    "default": "",
                    "description": "LLM model override for the CallAgent (leave empty to use the control plane default).",
                },
                {
                    "name": "call_agent_enabled_tools",
                    "type": "string",
                    "default": "",
                    "description": "Comma-separated tool names the CallAgent may use (empty = no tools).",
                },
            ],
        }
