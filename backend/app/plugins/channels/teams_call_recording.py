"""Teams call recording over Graph: one recordResponse at a time, its completion handed to the processing worker."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class TeamsCallRecording:
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
    def _on_recording_completed(self, call_id: str, resource_data: dict) -> None:
        # The recording goes to the processing worker, which restarts recording once the bot answered.
        self._recording_active.pop(call_id, None)
        recording_location = str(resource_data.get("recordingLocation") or "")
        completion_reason = str(resource_data.get("completionReason") or "")
        logger.info("Recording completed for call %s (reason=%s): %s", call_id, completion_reason,
                    recording_location[:80] if recording_location else "no URL")
        # Graph does not allow recordResponse during playPrompt: a recording that ends while the bot speaks is dropped.
        from ...services.teams_calling.call_session_state import is_bot_speaking

        if is_bot_speaking(call_id):
            logger.info("Recording completed for call %s while bot is speaking — suppressing", call_id)
        elif recording_location and call_id in self._active_calls:
            self._enqueue_recording(call_id, recording_location, resource_data, completion_reason)
        elif not recording_location:
            logger.warning("recordOperation completed but no recordingLocation for call %s (reason=%s)", call_id,
                           completion_reason)
            if call_id not in self._active_calls:
                return
            if completion_reason in ("maxSilenceReached", "mediaReceiveTimedOut", "initialSilenceTimedOut"):

                async def _delayed_restart(cid: str):
                    await asyncio.sleep(1.0)  # after silence, a short pause before the next recording
                    if cid in self._active_calls:
                        await self._start_record(cid)

                asyncio.create_task(_delayed_restart(call_id))
            else:
                asyncio.create_task(self._start_record(call_id))
    def _enqueue_recording(self, call_id: str, recording_location: str, resource_data: dict,
                           completion_reason: str) -> None:
        call_info = self._active_calls[call_id]
        try:
            from ...services.teams_calling.recording_processor import enqueue_recording

            enqueue_recording({
                "call_id": call_id,
                "recording_location": recording_location,
                "recording_access_token": str(resource_data.get("recordingAccessToken") or ""),
                "channel_id": call_info["channel_id"],
                "project_id": call_info["project_id"],
                "https_base": call_info["https_base"],
                "caller_display_name": call_info.get("caller_display_name", ""),
                "caller_id": call_info.get("caller_id", ""),
                "is_direct_call": call_info.get("is_direct_call", False),
                "completion_reason": completion_reason,
            })
            logger.info("Recording enqueued for %s — waiting for worker to restart recording after response", call_id)
        except Exception:
            logger.exception("Failed to enqueue recording for call %s", call_id)
            asyncio.create_task(self._start_record(call_id))
    def _on_prompt_played(self, call_id: str) -> None:
        # No restart during enrollment or the bot's own answer: those restart recording after their playback.
        from ...services.teams_calling.call_session_state import is_bot_speaking, signal_playback_done
        from ...services.teams_calling.enrollment_flow import is_enrollment_active

        if is_enrollment_active(call_id):
            logger.info("playPrompt completed for call %s — enrollment active, NOT restarting recording", call_id)
        elif is_bot_speaking(call_id):
            logger.info("playPrompt completed for call %s — signaling worker (bot response done)", call_id)
            signal_playback_done(call_id)
        else:
            logger.info("playPrompt completed for call %s — starting recording", call_id)
            if call_id in self._active_calls:
                asyncio.create_task(self._start_record(call_id))
    def _on_recording_failed(self, call_id: str, status: str) -> None:
        # Restarted, but not while the bot speaks: its playPrompt cancels recordings and restarts them itself.
        self._recording_active.pop(call_id, None)
        from ...services.teams_calling.call_session_state import is_bot_speaking

        if is_bot_speaking(call_id):
            logger.info("Recording %s for call %s while bot is speaking — NOT restarting (playPrompt handler will "
                        "restart)", status, call_id)
        elif call_id in self._active_calls:
            logger.warning("Recording %s for call %s — restarting", status, call_id)
            asyncio.create_task(self._start_record(call_id))
