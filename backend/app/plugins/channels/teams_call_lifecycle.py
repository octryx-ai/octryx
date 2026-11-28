"""Teams calls from the Graph notifications: incoming, established and terminated calls, the caller and the call proxy's answer."""

import asyncio
import logging
import sys
from urllib.parse import quote, urlencode

from ...services.person_log_ref import person_log_ref

logger = logging.getLogger(__name__)


_CALLING_MODE_CALL_PROXY = "call_proxy"  # an external call proxy answers the call and streams its audio


_CALLING_MODE_GRAPH_RECORDING = "graph_recording"


_SUPPORTED_CALLING_MODES = {_CALLING_MODE_CALL_PROXY, _CALLING_MODE_GRAPH_RECORDING}


def _notif_debug(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class TeamsCallLifecycle:
    def _build_calling_response(self, call_id: str) -> dict | None:
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
        audio_token = issue_call_audio_token(call_id, channel_id=channel_id, project_id=project_id)
        query = urlencode({"project_id": project_id, "channel_id": channel_id, "token": audio_token})
        audio_ws_url = f"{ws_base}/api/v1/teams/calls/{quote(call_id, safe='')}/audio/ws?{query}"
        logger.info("Answering call %s via the call proxy with a per-call audio WS token", call_id)
        return {"audioWebSocketUri": audio_ws_url}
    def _https_base(self) -> str:
        return self._calling_https_base()
    def _callback_uri(self) -> str:
        return f"{self._https_base()}/api/v1/channels/{self.config.get('__channel_id', '')}/webhook"
    async def _answer_graph_call(self, call_id: str) -> None:
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
    async def _fetch_caller_display_name(self, call_id: str) -> None:
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
    @staticmethod
    def _extract_call_id(resource: str) -> str:
        parts = resource.strip("/").split("/")
        try:
            idx = parts.index("calls")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except ValueError:
            pass
        return resource.rstrip("/").split("/")[-1]
    async def _handle_graph_calling_notification(self, payload: dict) -> dict:
        if not self.calling_enabled:
            logger.info("Ignoring Graph calling notification because Teams calling is disabled")
            return {"status": "ignored", "reason": "calling_disabled"}
        for notif in payload.get("value") or []:
            change_type = str(notif.get("changeType") or "")
            resource_data = notif.get("resourceData") or {}
            resource = str(notif.get("resourceUrl") or notif.get("resource") or "")
            odata_type = str(resource_data.get("@odata.type") or "")
            call_id = self._extract_call_id(resource)
            logger.info("Graph notification: changeType=%s odata=%s state=%s call_id=%s", change_type, odata_type,
                        resource_data.get("state", ""), call_id)
            if not call_id:
                continue
            _notif_debug(f"[NOTIF DETAIL] call_id={call_id} changeType={change_type} odata={odata_type} "
                         f"state={resource_data.get('state', '')} status={resource_data.get('status', '')} "
                         f"active_calls={list(self._active_calls.keys())[:3]}")
            # Incoming calls log only the resourceData keys; the provider payload itself is never logged.
            if resource_data.get("state") == "incoming":
                _notif_debug(f"[NOTIF INCOMING FULL] keys={list(resource_data.keys())}")
            response = await self._on_call_event(notif, call_id, change_type, odata_type, resource_data)
            if response is not None:
                return response
        return {"status": "accepted"}
    async def _on_call_event(self, notif: dict, call_id: str, change_type: str, odata_type: str,
                             resource_data: dict) -> dict | None:
        # The HTTP answer an incoming call in call-proxy mode needs, else None (the next notification).
        state, status = resource_data.get("state"), resource_data.get("status")
        if change_type == "created" and state == "incoming":
            return self._on_incoming_call(notif, call_id, resource_data)
        if state == "established" and call_id in self._active_calls:
            self._on_call_established(call_id)
        elif odata_type == "#microsoft.graph.recordOperation" and status == "completed":
            self._on_recording_completed(call_id, resource_data)
        elif odata_type == "#microsoft.graph.playPromptOperation" and status == "completed":
            self._on_prompt_played(call_id)
        elif odata_type == "#microsoft.graph.recordOperation" and status in ("failed", "cancelled"):
            self._on_recording_failed(call_id, status)
        elif state == "terminated":
            self._on_call_terminated(call_id)
        return None
    @staticmethod
    def _caller_of(notif: dict, resource_data: dict) -> tuple[str, str]:
        # Graph may put the caller in "source", "incomingContext" or the notification's own resourceData.
        caller_user = ((resource_data.get("source") or {}).get("identity") or {}).get("user") or {}
        caller_display_name = str(caller_user.get("displayName") or "").strip()
        caller_id = str(caller_user.get("id") or "").strip()
        if not caller_display_name:
            incoming_ctx = resource_data.get("incomingContext") or {}
            if not caller_id:
                caller_id = str(incoming_ctx.get("sourceParticipantId") or "").strip()
            notif_source = notif.get("resourceData", {}).get("source") or {}
            caller_display_name = str(
                notif_source.get("identity", {}).get("user", {}).get("displayName") or ""
            ).strip()
        return caller_display_name, caller_id
    def _on_incoming_call(self, notif: dict, call_id: str, resource_data: dict) -> dict | None:
        # Store the call and answer it, or hand the call proxy its audio stream address.
        caller_display_name, caller_id = self._caller_of(notif, resource_data)
        _notif_debug(f"[NOTIF CALLER DEBUG] call_id={call_id} resourceData keys={list(resource_data.keys())} "
                     f"caller={person_log_ref(caller_display_name)}")
        # A group call or meeting carries meetingInfo; a direct 1:1 call does not.
        is_direct_call = resource_data.get("meetingInfo") is None
        if caller_display_name:
            logger.info("Incoming call %s from %s (id=%s, direct=%s)", call_id, person_log_ref(caller_display_name),
                        person_log_ref(caller_id), is_direct_call)
        self._active_calls[call_id] = {
            "channel_id": str(self.config.get("__channel_id", "")),
            "project_id": str(self.config.get("__channel_project_id", "")),
            "https_base": self._https_base(),
            "caller_display_name": caller_display_name,
            "caller_id": caller_id,
            "is_direct_call": is_direct_call,
        }
        if self.calling_mode != _CALLING_MODE_CALL_PROXY:
            asyncio.create_task(self._answer_graph_call(call_id))  # graph_recording: answer, then recordResponse
            return None
        # Streaming mode: the audioWebSocketUri goes back in the HTTP response, where the call proxy streams to.
        resp = self._build_calling_response(call_id)
        if resp:
            logger.info("Returning audioWebSocketUri to the call proxy for call %s", call_id)
            return resp
        logger.warning("Could not build audioWebSocketUri for call %s — Graph recording fallback is disabled", call_id)
        self._active_calls.pop(call_id, None)
        return {"status": "ignored", "reason": "graph_recording_disabled"}
    def _on_call_established(self, call_id: str) -> None:
        # Fetch the caller's name, then (graph_recording) play the greeting and start recording.
        call_info = self._active_calls[call_id]
        if call_info.get("recording_started"):
            return
        call_info["recording_started"] = True
        if self.calling_mode == _CALLING_MODE_GRAPH_RECORDING:
            logger.info("Call %s established — fetching caller name then playing greeting", call_id)

            async def _greet_with_name(cid: str):
                if not self._active_calls.get(cid, {}).get("caller_display_name"):
                    await self._fetch_caller_display_name(cid)
                await self._play_greeting_then_record(cid)

            asyncio.create_task(_greet_with_name(call_id))
            return
        if not call_info.get("caller_display_name"):
            asyncio.create_task(self._fetch_caller_display_name(call_id))  # the name, for later use
        logger.info("Call %s established in call_proxy mode — waiting for audio stream", call_id)
    def _on_call_terminated(self, call_id: str) -> None:
        self._active_calls.pop(call_id, None)
        self._recording_active.pop(call_id, None)
        logger.info("Call %s terminated — cleaned up", call_id)
        try:
            from ...services.teams_calling.call_session_state import close_call_db_session

            asyncio.create_task(close_call_db_session(call_id))
        except Exception:
            logger.exception("Failed to close call DB session for %s", call_id)
