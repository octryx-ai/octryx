# ruff: noqa: E501
"""Background recording processor for Teams calls."""

from __future__ import annotations

import asyncio
import logging
import re
import sys
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
    call_id = item["call_id"]
    channel_id = item.get("channel_id", "")
    recording_location = item["recording_location"]
    recording_access_token = item["recording_access_token"]
    _debug(f"_process_one_recording called for {call_id}, caller={person_log_ref(item.get('caller_display_name'))}, "
           f"direct={item.get('is_direct_call', False)}, has_location={bool(recording_location)}")

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


def _debug(message: str) -> None:
    print(f"[CALL DEBUG] {message}", file=sys.stderr, flush=True)


async def _process_downloaded_recording(item: dict, audio_bytes: bytes, db: AsyncSession) -> None:
    call_id = item["call_id"]
    channel_id = item.get("channel_id", "")
    project_id = item.get("project_id", "")
    https_base = item.get("https_base", "")
    is_direct_call = item.get("is_direct_call", False)

    from ...services.speaker.voice_enrollment import get_enrollment_session

    enrollment_session = get_enrollment_session(call_id)
    if enrollment_session:
        _debug(f"Enrollment recording received for {call_id}, speaker={person_log_ref(enrollment_session.speaker_name)}")
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

    text = await _transcribe(call_id, channel_id, audio_bytes, db)
    if text is None:
        return

    call_state = get_call_state(call_id)
    call_state.project_id = project_id or call_state.project_id
    call_state.channel_id = channel_id or call_state.channel_id
    speaker_name, speaker_source = await _speaker_of(item, audio_bytes)
    wake_word_decision = await _wake_word_decision(text, channel_id, is_direct_call, db)

    # Always add transcript segment (user said something)
    chunk_duration_ms = int(len(audio_bytes) * 1000 / 32000)  # rough estimate: 16kHz 16-bit mono
    call_state.add_user_segment(
        text, duration_ms=chunk_duration_ms, speaker_name=speaker_name, speaker_source=speaker_source
    )

    if not wake_word_decision.should_respond:
        _debug("No wake word → restarting recording")
        logger.debug("Call %s: no wake word in chars=%d — restarting recording", call_id, len(text))
        await restart_recording(call_id, channel_id)
        return

    command_text = wake_word_decision.command_text
    _debug(f"Wake word matched, calling agent with: chars={len(command_text)}")
    logger.info("Call %s: wake word matched, command chars=%d", call_id, len(command_text))
    if await _handled_enrollment_command(item, command_text, db):
        return

    # The call's chat session and its owner (``call_owner.py``); a refused owner starts no turn.
    call_session = await ensure_call_db_session(call_id, project_id, channel_id, db, caller_id=item.get("caller_id", ""))
    if call_session.state is not None:
        await restart_recording(call_id, channel_id)
        return
    await _answer(item, text, command_text, call_session.session_id, db)


async def _transcribe(call_id: str, channel_id: str, audio_bytes: bytes, db: AsyncSession) -> str | None:
    # None: the recording restarted (no STT, a failed or empty transcription).
    _debug(f"Starting STT for call {call_id} ({len(audio_bytes)} bytes)")
    stt = await get_stt_service(db)
    if stt is None:
        _debug(f"STT not available for call {call_id}")
        await restart_recording(call_id, channel_id)
        return None
    try:
        text = (await stt.transcribe(audio_bytes, filename="recording.wav") or "").strip()
        _debug(f"STT result for {call_id}: chars={len(text)}")
    except Exception as _stt_err:
        _debug(f"STT EXCEPTION for {call_id}: error_type={type(_stt_err).__name__}")
        logger.exception("STT failed for call %s", call_id)
        await restart_recording(call_id, channel_id)
        return None
    if not text:
        _debug(f"Empty transcription for {call_id} — restarting")
        await restart_recording(call_id, channel_id)
        return None
    _debug(f"Call {call_id} STT: chars={len(text)}")
    logger.info("Call %s STT: chars=%d", call_id, len(text))
    return text


async def _speaker_of(item: dict, audio_bytes: bytes) -> tuple[str | None, str]:
    project_id = item.get("project_id", "")
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
                _debug(f"Diarization: {diar_result.num_speakers} speakers, dominant="
                       f"{person_log_ref(speaker_name) if speaker_name else dominant.speaker_label}")
    except ImportError:
        pass  # pyannote not available
    except Exception as _diar_err:
        _debug(f"Diarization failed (non-critical): error_type={type(_diar_err).__name__}")
    if speaker_name:
        return speaker_name, "diarization"
    # Fallback: In direct calls, use the caller display name from Teams API
    if item.get("is_direct_call", False) and item.get("caller_display_name", ""):
        return item["caller_display_name"], "teams_api"
    return None, ""


async def _wake_word_decision(text: str, channel_id: str, is_direct_call: bool, db: AsyncSession):
    # In direct (1:1) calls no wake word is required: the user called the bot intentionally.
    _debug(f"Loading wake word policy for channel_id={repr(channel_id)}, is_direct_call={is_direct_call}")
    wake_word_policy = await get_wake_word_policy_for_channel(channel_id, db)
    if is_direct_call:
        _debug(f"Direct call → wake word skipped, full text is command: chars={len(text)}")
        return WakeWordPolicy(require_wake_word=False).evaluate(text)
    decision = wake_word_policy.evaluate(text)
    _debug(f"Wake word: require={wake_word_policy.require_wake_word} words={wake_word_policy.wake_words} "
           f"should_respond={decision.should_respond}")
    return decision


async def _handled_enrollment_command(item: dict, command_text: str, db: AsyncSession) -> bool:
    # A voice enrollment command ("register my voice [as Alice]") works only in a direct (1:1) call.
    from ...plugins import plugin_manager
    from ...services.speaker.voice_enrollment import _UNKNOWN_CALLER_PLACEHOLDER, detect_enrollment_command

    call_id, channel_id = item["call_id"], item.get("channel_id", "")
    project_id, https_base = item.get("project_id", ""), item.get("https_base", "")
    caller_display_name, caller_id = item.get("caller_display_name", ""), item.get("caller_id", "")
    enrollment_name = detect_enrollment_command(command_text, caller_display_name=caller_display_name)
    if not enrollment_name:
        return False
    if not item.get("is_direct_call", False):
        _debug("Enrollment rejected: not a direct call")
        rejection = "Voice registration only works when you call me directly, not in a group call."
        provider = await get_tts_provider(db, project_id=project_id or None)
        plugin = plugin_manager.get_channel(channel_id)
        if provider and plugin and hasattr(plugin, "_play_prompt"):
            try:
                await plugin._play_prompt(call_id, await _stored_audio_url(provider, rejection, https_base, call_id))
            except Exception:
                pass
        await restart_recording(call_id, channel_id)
        return True
    # The placeholder name: the caller's name the plugin may have fetched meanwhile (Graph participants API).
    if enrollment_name == _UNKNOWN_CALLER_PLACEHOLDER:
        plugin = plugin_manager.get_channel(channel_id)
        if plugin and hasattr(plugin, "_active_calls"):
            resolved = plugin._active_calls.get(call_id, {}).get("caller_display_name", "")
            if resolved:
                enrollment_name = resolved.strip()
                _debug(f"Resolved caller name from API: {person_log_ref(enrollment_name)}")
            else:
                enrollment_name = caller_id[:8] if caller_id else "Speaker"
                _debug(f"Caller name unknown, using fallback: {person_log_ref(enrollment_name)}")
    _debug(f"Voice enrollment command detected: name={person_log_ref(enrollment_name)} "
           f"(caller={person_log_ref(caller_display_name)})")
    await start_enrollment_flow(call_id=call_id, channel_id=channel_id, project_id=project_id,
                                speaker_name=enrollment_name, https_base=https_base, db=db)
    return True


async def _stored_audio_url(provider, text: str, https_base: str, call_id: str) -> str:
    audio = await provider.synthesize(text, voice="alloy", speed=1.0)
    file_id = str(uuid.uuid4())
    _temp_audio[file_id] = audio
    return f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"


async def _play_thinking(item: dict, plugin, db: AsyncSession):
    # The TTS provider when the thinking message was spoken, else None.
    call_id, channel_id, project_id = item["call_id"], item.get("channel_id", ""), item.get("project_id", "")
    thinking_message = await get_thinking_message(channel_id, db)
    if not (thinking_message and plugin and hasattr(plugin, "_play_prompt")):
        return None
    provider = await get_tts_provider(db, project_id=project_id or None)
    if provider:
        try:
            await plugin._play_prompt(call_id, await _stored_audio_url(provider, thinking_message,
                                                                       item.get("https_base", ""), call_id))
            _debug(f"Thinking message played for {call_id}")
        except Exception as _think_err:
            _debug(f"Thinking TTS failed: error_type={type(_think_err).__name__}")
    return provider


def _voice_text(response_text: str) -> str:
    # Markdown the models write is not spoken, and a voice answer stays near 250 characters (about 15 s).
    response_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", response_text)
    response_text = re.sub(r"\*([^*]+)\*", r"\1", response_text)
    response_text = re.sub(r"^#+\s*", "", response_text, flags=re.MULTILINE)
    response_text = re.sub(r"^[-*]\s+", "", response_text, flags=re.MULTILINE)
    response_text = response_text.replace("\n\n", " ").replace("\n", " ").strip()
    if len(response_text) > 250:
        cut_at = response_text.rfind(".", 0, 250)
        response_text = response_text[: cut_at + 1] if cut_at > 50 else response_text[:250].rsplit(" ", 1)[0] + "."
        _debug(f"Response truncated to {len(response_text)} chars for voice")
    return response_text


async def _answer(item: dict, text: str, command_text: str, db_session_id: str | None, db: AsyncSession) -> None:
    from ...plugins import plugin_manager

    call_id, channel_id, project_id = item["call_id"], item.get("channel_id", ""), item.get("project_id", "")
    plugin = plugin_manager.get_channel(channel_id)
    # Mark bot as "speaking" so playPromptOperation completed won't auto-restart recording
    _playback_locks[call_id] = asyncio.Event()
    provider = await _play_thinking(item, plugin, db)
    response_text = await agent_response(command_text, call_id, channel_id, db, project_id or None)
    _debug(f"Agent response: chars={len(response_text or '')}")
    if not response_text:
        _debug("Empty agent response → restarting recording")
        await _done(call_id, channel_id)
        return
    response_text = _voice_text(response_text)
    logger.info("Call %s agent response: chars=%d", call_id, len(response_text))
    if db_session_id:
        await add_call_message(db_session_id, "user", text, db)
        await add_call_message(db_session_id, "assistant", response_text, db)
        await db.commit()
    provider = provider or await get_tts_provider(db, project_id=project_id or None)
    if provider is None:
        logger.warning("TTS not available for call %s", call_id)
        await _done(call_id, channel_id)
        return
    try:
        audio_out = await provider.synthesize(response_text, voice="alloy", speed=1.0)
    except Exception:
        logger.exception("TTS failed for call %s", call_id)
        await _done(call_id, channel_id)
        return
    await _play_answer(item, plugin, audio_out)


async def _play_answer(item: dict, plugin, audio_out: bytes) -> None:
    call_id, channel_id, https_base = item["call_id"], item.get("channel_id", ""), item.get("https_base", "")
    playback_duration = estimate_wav_duration(audio_out)
    _debug(f"Response audio: {len(audio_out)} bytes, estimated duration: {playback_duration:.1f}s")
    file_id = str(uuid.uuid4())
    _temp_audio[file_id] = audio_out
    audio_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"
    logger.info("Call %s TTS stored at %s (%.1fs)", call_id, audio_url, playback_duration)
    if not (plugin and hasattr(plugin, "_play_prompt")):
        logger.warning("No plugin for channel %s — cannot play prompt for call %s", channel_id, call_id)
        await _done(call_id, channel_id)
        return
    # A fresh event for the answer (the thinking message may have set the old one): the playPromptOperation
    # completed notification ends the wait, else a timeout after the expected duration.
    _playback_locks[call_id] = asyncio.Event()
    await plugin._play_prompt(call_id, audio_url)
    evt = _playback_locks.get(call_id)
    if evt:
        max_wait = playback_duration + 2.0
        _debug(f"Waiting for playback-done event (timeout={max_wait:.1f}s)")
        try:
            await asyncio.wait_for(evt.wait(), timeout=max_wait)
            _debug(f"Playback-done event received for {call_id}")
        except TimeoutError:
            _debug(f"Playback-done event TIMEOUT for {call_id} after {max_wait:.1f}s — proceeding anyway")
    else:
        wait_time = playback_duration + 0.5
        _debug(f"No event, sleeping {wait_time:.1f}s for playback")
        await asyncio.sleep(wait_time)
    await _done(call_id, channel_id)


async def _done(call_id: str, channel_id: str) -> None:
    _playback_locks.pop(call_id, None)
    await restart_recording(call_id, channel_id)
