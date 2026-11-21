# ruff: noqa: E501
"""Background recording processor for Teams calls.

TeamsPlugin enqueues completed Graph recordOperation results here. A single
background worker downloads each recording, routes it through enrollment
detection, STT, speaker diarization, wake word evaluation, agent invocation,
and TTS playback, then restarts the Graph recording cycle.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import async_session_factory
from ...services.stt import get_stt_service
from ...services.tts import get_tts_provider
from ..person_log_ref import person_log_ref
from .agent_orchestration import agent_response
from .audio_pipeline import estimate_wav_duration, restart_recording
from .call_session_state import (
    _playback_locks,
    _temp_audio,
    add_call_message,
    ensure_call_db_session,
    get_call_state,
)
from .channel_context import get_thinking_message, get_wake_word_policy_for_channel
from .enrollment_flow import handle_enrollment_sample, start_enrollment_flow
from .recording_spool import spooled_recording
from .wake_word import WakeWordPolicy

logger = logging.getLogger(__name__)

_recording_queue: asyncio.Queue[dict] = asyncio.Queue()
_worker_task: asyncio.Task | None = None


def enqueue_recording(item: dict) -> None:
    """Called by TeamsPlugin when a Graph recordOperation completes."""
    _recording_queue.put_nowait(item)
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        try:
            loop = asyncio.get_running_loop()
            _worker_task = loop.create_task(_recording_processor_worker())
            logger.info("Teams call recording processor started")
        except RuntimeError:
            pass  # No running loop yet — worker will start on first enqueue


async def _recording_processor_worker() -> None:
    while True:
        try:
            item = await asyncio.wait_for(_recording_queue.get(), timeout=300)
        except TimeoutError:
            continue
        try:
            async with async_session_factory() as db:
                await _process_one_recording(item, db)
        except Exception:
            logger.exception("Recording processor error for call %s", item.get("call_id"))


async def _process_one_recording(item: dict, db: AsyncSession) -> None:
    import sys as _sys

    call_id = item["call_id"]
    channel_id = item.get("channel_id", "")
    recording_location = item["recording_location"]
    recording_access_token = item["recording_access_token"]
    print(
        f"[CALL DEBUG] _process_one_recording called for {call_id}, caller={person_log_ref(item.get('caller_display_name'))}, direct={item.get('is_direct_call', False)}, has_location={bool(recording_location)}",
        file=_sys.stderr,
        flush=True,
    )

    # Download the recording
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                recording_location,
                headers={"Authorization": f"Bearer {recording_access_token}"},
            )
            resp.raise_for_status()
            audio_bytes = resp.content
    except Exception:
        logger.exception("Failed to download recording for call %s", call_id)
        await restart_recording(call_id, channel_id)
        return

    # The recording is spooled owner-only in the data directory while the turn is processed,
    # and removed afterwards whatever the outcome.
    with spooled_recording(audio_bytes):
        await _process_downloaded_recording(item, audio_bytes, db)


async def _process_downloaded_recording(item: dict, audio_bytes: bytes, db: AsyncSession) -> None:
    import sys as _sys

    call_id = item["call_id"]
    channel_id = item.get("channel_id", "")
    project_id = item.get("project_id", "")
    https_base = item.get("https_base", "")
    caller_display_name = item.get("caller_display_name", "")
    caller_id = item.get("caller_id", "")
    is_direct_call = item.get("is_direct_call", False)

    # =====================================================
    # CHECK: Is this a voice enrollment sample recording?
    # =====================================================
    from ...services.speaker.voice_enrollment import (
        get_enrollment_session,
    )

    enrollment_session = get_enrollment_session(call_id)
    if enrollment_session:
        print(
            f"[CALL DEBUG] Enrollment recording received for {call_id}, speaker={person_log_ref(enrollment_session.speaker_name)}",
            file=_sys.stderr,
            flush=True,
        )
        await handle_enrollment_sample(
            call_id=call_id,
            channel_id=channel_id,
            project_id=enrollment_session.project_id,
            speaker_name=enrollment_session.speaker_name,
            audio_bytes=audio_bytes,
            https_base=https_base,
            db=db,
        )
        return

    # STT
    print(f"[CALL DEBUG] Starting STT for call {call_id} ({len(audio_bytes)} bytes)", file=_sys.stderr, flush=True)
    stt = await get_stt_service(db)
    if stt is None:
        print(f"[CALL DEBUG] STT not available for call {call_id}", file=_sys.stderr, flush=True)
        await restart_recording(call_id, channel_id)
        return

    try:
        text = await stt.transcribe(audio_bytes, filename="recording.wav")
        text = (text or "").strip()
        print(f"[CALL DEBUG] STT result for {call_id}: chars={len(text)}", file=_sys.stderr, flush=True)
    except Exception as _stt_err:
        print(
            f"[CALL DEBUG] STT EXCEPTION for {call_id}: error_type={type(_stt_err).__name__}",
            file=_sys.stderr,
            flush=True,
        )
        logger.exception("STT failed for call %s", call_id)
        await restart_recording(call_id, channel_id)
        return

    if not text:
        print(f"[CALL DEBUG] Empty transcription for {call_id} — restarting", file=_sys.stderr, flush=True)
        await restart_recording(call_id, channel_id)
        return

    print(f"[CALL DEBUG] Call {call_id} STT: chars={len(text)}", file=_sys.stderr, flush=True)
    logger.info("Call %s STT: chars=%d", call_id, len(text))

    # Agent
    call_state = get_call_state(call_id)
    call_state.project_id = project_id or call_state.project_id
    call_state.channel_id = channel_id or call_state.channel_id

    # --- Speaker Diarization (identify who is speaking) ---
    speaker_name: str | None = None
    try:
        from ...services.speaker.diarization import diarize_audio, get_enrolled_speakers

        # Only run diarization if speakers are enrolled for this project
        if project_id and get_enrolled_speakers(project_id):
            diar_result = await diarize_audio(audio_bytes, project_id=project_id)
            if diar_result.segments:
                # Use the dominant speaker in this segment
                dominant = max(diar_result.segments, key=lambda s: s.end_sec - s.start_sec)
                speaker_name = dominant.speaker_name
                print(
                    f"[CALL DEBUG] Diarization: {diar_result.num_speakers} speakers, dominant={person_log_ref(speaker_name) if speaker_name else dominant.speaker_label}",
                    file=_sys.stderr,
                    flush=True,
                )
    except ImportError:
        pass  # pyannote not available
    except Exception as _diar_err:
        print(
            f"[CALL DEBUG] Diarization failed (non-critical): error_type={type(_diar_err).__name__}",
            file=_sys.stderr,
            flush=True,
        )

    # Fallback: In direct calls, use the caller display name from Teams API
    speaker_source = ""
    if speaker_name:
        speaker_source = "diarization"
    elif is_direct_call and caller_display_name:
        speaker_name = caller_display_name
        speaker_source = "teams_api"

    # Wake word evaluation — load channel config for wake word settings
    # IMPORTANT: In direct (1:1) calls, wake word is NOT required — user called the bot intentionally.
    print(
        f"[CALL DEBUG] Loading wake word policy for channel_id={repr(channel_id)}, is_direct_call={is_direct_call}",
        file=_sys.stderr,
        flush=True,
    )
    wake_word_policy = await get_wake_word_policy_for_channel(channel_id, db)

    if is_direct_call:
        # Direct call: no wake word needed, entire text is the command
        wake_word_decision = WakeWordPolicy(require_wake_word=False).evaluate(text)
        print(
            f"[CALL DEBUG] Direct call → wake word skipped, full text is command: chars={len(text)}",
            file=_sys.stderr,
            flush=True,
        )
    else:
        wake_word_decision = wake_word_policy.evaluate(text)
        print(
            f"[CALL DEBUG] Wake word: require={wake_word_policy.require_wake_word} words={wake_word_policy.wake_words} should_respond={wake_word_decision.should_respond}",
            file=_sys.stderr,
            flush=True,
        )

    # Always add transcript segment (user said something)
    chunk_duration_ms = int(len(audio_bytes) * 1000 / 32000)  # rough estimate: 16kHz 16-bit mono
    call_state.add_user_segment(
        text, duration_ms=chunk_duration_ms, speaker_name=speaker_name, speaker_source=speaker_source
    )

    if not wake_word_decision.should_respond:
        print("[CALL DEBUG] No wake word → restarting recording", file=_sys.stderr, flush=True)
        logger.debug("Call %s: no wake word in chars=%d — restarting recording", call_id, len(text))
        await restart_recording(call_id, channel_id)
        return

    command_text = wake_word_decision.command_text
    print(
        f"[CALL DEBUG] Wake word matched, calling agent with: chars={len(command_text)}", file=_sys.stderr, flush=True
    )
    logger.info("Call %s: wake word matched, command chars=%d", call_id, len(command_text))

    # =====================================================
    # CHECK: Is this a voice enrollment command?
    # e.g., "register my voice" or "register my voice as Alice"
    # Only allowed in direct (1:1) calls, not group calls.
    # =====================================================
    from ...services.speaker.voice_enrollment import (
        _UNKNOWN_CALLER_PLACEHOLDER,
        detect_enrollment_command,
    )

    enrollment_name = detect_enrollment_command(command_text, caller_display_name=caller_display_name)
    if enrollment_name:
        if not is_direct_call:
            # Enrollment only works in 1:1 calls — tell the user
            print("[CALL DEBUG] Enrollment rejected: not a direct call", file=_sys.stderr, flush=True)
            _play_rejection = "Voice registration only works when you call me directly, not in a group call."
            provider = await get_tts_provider(db, project_id=project_id or None)
            from ...plugins import plugin_manager as _pm

            _plugin = _pm.get_channel(channel_id)
            if provider and _plugin and hasattr(_plugin, "_play_prompt"):
                try:
                    _rej_audio = await provider.synthesize(_play_rejection, voice="alloy", speed=1.0)
                    _rej_id = str(uuid.uuid4())
                    _temp_audio[_rej_id] = _rej_audio
                    _rej_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{_rej_id}"
                    await _plugin._play_prompt(call_id, _rej_url)
                except Exception:
                    pass
            await restart_recording(call_id, channel_id)
            return

        # Resolve the placeholder name: try to get caller name from the plugin's active_calls
        # (may have been fetched asynchronously via Graph participants API)
        if enrollment_name == _UNKNOWN_CALLER_PLACEHOLDER:
            from ...plugins import plugin_manager as _pm2

            _plugin2 = _pm2.get_channel(channel_id)
            if _plugin2 and hasattr(_plugin2, "_active_calls"):
                _call_info = _plugin2._active_calls.get(call_id, {})
                _resolved_name = _call_info.get("caller_display_name", "")
                if _resolved_name:
                    enrollment_name = _resolved_name.strip()  # Full name
                    print(
                        f"[CALL DEBUG] Resolved caller name from API: {person_log_ref(enrollment_name)}", file=_sys.stderr, flush=True
                    )
                else:
                    # Still unknown — use caller_id as fallback or a generic name
                    enrollment_name = caller_id[:8] if caller_id else "Speaker"
                    print(
                        f"[CALL DEBUG] Caller name unknown, using fallback: {person_log_ref(enrollment_name)}",
                        file=_sys.stderr,
                        flush=True,
                    )

        print(
            f"[CALL DEBUG] Voice enrollment command detected: name={person_log_ref(enrollment_name)} (caller={person_log_ref(caller_display_name)})",
            file=_sys.stderr,
            flush=True,
        )
        await start_enrollment_flow(
            call_id=call_id,
            channel_id=channel_id,
            project_id=project_id,
            speaker_name=enrollment_name,
            https_base=https_base,
            db=db,
        )
        return

    # The call's chat session and its owner (``call_owner.py``); a refused owner starts no turn.
    call_session = await ensure_call_db_session(call_id, project_id, channel_id, db, caller_id=caller_id)
    if call_session.state is not None:
        await restart_recording(call_id, channel_id)
        return
    db_session_id = call_session.session_id

    # --- Play Thinking Message immediately (before LLM processing) ---
    from ...plugins import plugin_manager

    plugin = plugin_manager.get_channel(channel_id)
    thinking_message = await get_thinking_message(channel_id, db)

    # Mark bot as "speaking" so playPromptOperation completed won't auto-restart recording
    _playback_locks[call_id] = asyncio.Event()

    if thinking_message and plugin and hasattr(plugin, "_play_prompt"):
        provider = await get_tts_provider(db, project_id=project_id or None)
        if provider:
            try:
                thinking_audio = await provider.synthesize(thinking_message, voice="alloy", speed=1.0)
                thinking_file_id = str(uuid.uuid4())
                _temp_audio[thinking_file_id] = thinking_audio
                thinking_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{thinking_file_id}"
                await plugin._play_prompt(call_id, thinking_url)
                print(f"[CALL DEBUG] Thinking message played for {call_id}", file=_sys.stderr, flush=True)
            except Exception as _think_err:
                print(
                    f"[CALL DEBUG] Thinking TTS failed: error_type={type(_think_err).__name__}",
                    file=_sys.stderr,
                    flush=True,
                )

    response_text = await agent_response(command_text, call_id, channel_id, db, project_id or None)
    print(f"[CALL DEBUG] Agent response: chars={len(response_text or '')}", file=_sys.stderr, flush=True)
    if not response_text:
        print("[CALL DEBUG] Empty agent response → restarting recording", file=_sys.stderr, flush=True)
        _playback_locks.pop(call_id, None)
        await restart_recording(call_id, channel_id)
        return

    # Truncate overly long responses for voice (max ~200 chars ≈ 15s speech)
    # Strip markdown artifacts that models sometimes generate
    import re as _re_strip

    response_text = _re_strip.sub(r"\*\*([^*]+)\*\*", r"\1", response_text)  # **bold** → bold
    response_text = _re_strip.sub(r"\*([^*]+)\*", r"\1", response_text)  # *italic* → italic
    response_text = _re_strip.sub(r"^#+\s*", "", response_text, flags=_re_strip.MULTILINE)  # # headers
    response_text = _re_strip.sub(r"^[-*]\s+", "", response_text, flags=_re_strip.MULTILINE)  # bullet points
    response_text = response_text.replace("\n\n", " ").replace("\n", " ").strip()

    # Hard limit: truncate at sentence boundary near 250 chars
    if len(response_text) > 250:
        cut_at = response_text.rfind(".", 0, 250)
        if cut_at > 50:
            response_text = response_text[: cut_at + 1]
        else:
            response_text = response_text[:250].rsplit(" ", 1)[0] + "."
        print(f"[CALL DEBUG] Response truncated to {len(response_text)} chars for voice", file=_sys.stderr, flush=True)

    logger.info("Call %s agent response: chars=%d", call_id, len(response_text))

    # Persist the turn as chat messages
    if db_session_id:
        await add_call_message(db_session_id, "user", text, db)
        await add_call_message(db_session_id, "assistant", response_text, db)
        await db.commit()

    # TTS the actual response
    if not provider:
        provider = await get_tts_provider(db, project_id=project_id or None)
    if provider is None:
        logger.warning("TTS not available for call %s", call_id)
        _playback_locks.pop(call_id, None)
        await restart_recording(call_id, channel_id)
        return

    try:
        audio_out = await provider.synthesize(response_text, voice="alloy", speed=1.0)
    except Exception:
        logger.exception("TTS failed for call %s", call_id)
        _playback_locks.pop(call_id, None)
        await restart_recording(call_id, channel_id)
        return

    # Calculate expected playback duration from WAV data
    playback_duration = estimate_wav_duration(audio_out)
    print(
        f"[CALL DEBUG] Response audio: {len(audio_out)} bytes, estimated duration: {playback_duration:.1f}s",
        file=_sys.stderr,
        flush=True,
    )

    # Store temp audio and build public URL
    file_id = str(uuid.uuid4())
    _temp_audio[file_id] = audio_out
    audio_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"
    logger.info("Call %s TTS stored at %s (%.1fs)", call_id, audio_url, playback_duration)

    # Play via Graph API
    if plugin and hasattr(plugin, "_play_prompt"):
        # Create a FRESH event for the response playback (thinking msg may have set old one)
        _playback_locks[call_id] = asyncio.Event()
        await plugin._play_prompt(call_id, audio_url)
        # Wait for playPromptOperation-completed notification (event-based)
        # OR fall back to duration-based timeout if notification doesn't arrive.
        evt = _playback_locks.get(call_id)
        if evt:
            max_wait = playback_duration + 2.0  # generous fallback timeout
            print(
                f"[CALL DEBUG] Waiting for playback-done event (timeout={max_wait:.1f}s)", file=_sys.stderr, flush=True
            )
            try:
                await asyncio.wait_for(evt.wait(), timeout=max_wait)
                print(f"[CALL DEBUG] Playback-done event received for {call_id}", file=_sys.stderr, flush=True)
            except TimeoutError:
                print(
                    f"[CALL DEBUG] Playback-done event TIMEOUT for {call_id} after {max_wait:.1f}s — proceeding anyway",
                    file=_sys.stderr,
                    flush=True,
                )
        else:
            # Fallback: no event available, use sleep
            wait_time = playback_duration + 0.5
            print(f"[CALL DEBUG] No event, sleeping {wait_time:.1f}s for playback", file=_sys.stderr, flush=True)
            await asyncio.sleep(wait_time)
        _playback_locks.pop(call_id, None)
        await restart_recording(call_id, channel_id)
    else:
        logger.warning("No plugin for channel %s — cannot play prompt for call %s", channel_id, call_id)
        _playback_locks.pop(call_id, None)
        await restart_recording(call_id, channel_id)
