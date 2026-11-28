"""Teams call audio: prompts played over Graph and the spoken greeting."""

import logging

from ...services.person_log_ref import person_log_ref

logger = logging.getLogger(__name__)


class TeamsCallMedia:
    async def _play_prompt(self, call_id: str, audio_url: str) -> None:
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
    async def _play_greeting_then_record(self, call_id: str) -> None:
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
    @staticmethod
    def _generate_greeting_wav() -> bytes:
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
