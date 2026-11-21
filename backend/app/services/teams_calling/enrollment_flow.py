# ruff: noqa: E501
"""Voice enrollment flow orchestration for Teams calls.

The pure enrollment logic (command detection, session state machine, beep
generation, instruction texts) lives in ``app.services.speaker.voice_enrollment``.
This module owns the Teams-call-specific orchestration around it: playing
instructions and beeps through the Graph API, recording the voice sample,
and enrolling the speaker from the recorded audio.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ...services.tts import get_tts_provider
from ..person_log_ref import person_log_ref
from .audio_pipeline import estimate_wav_duration, restart_recording
from .call_session_state import _playback_locks, _temp_audio

logger = logging.getLogger(__name__)


def is_enrollment_active(call_id: str) -> bool:
    """Check if a voice enrollment session is active for this call.

    Used by TeamsPlugin to avoid auto-restarting recordings during enrollment.
    """
    from ...services.speaker.voice_enrollment import get_enrollment_session

    return get_enrollment_session(call_id) is not None


async def start_enrollment_flow(
    call_id: str,
    channel_id: str,
    project_id: str,
    speaker_name: str,
    https_base: str,
    db: AsyncSession,
) -> None:
    """Start the voice enrollment flow: play instructions + beep, then record voice sample.

    Flow:
    1. Play TTS instruction: asking the person to speak after the beep
    2. Play a beep tone
    3. Start a longer recording (15s, relaxed silence timeouts)
    4. The next recording will be handled by handle_enrollment_sample
    """
    import sys as _sys

    from ...plugins import plugin_manager
    from ...services.speaker.voice_enrollment import (
        generate_beep,
        get_enrollment_instruction_text,
        start_enrollment,
    )

    print(f"[CALL DEBUG] Starting enrollment flow for {person_log_ref(speaker_name)} on call {call_id}", file=_sys.stderr, flush=True)

    # Register the enrollment session
    start_enrollment(call_id, speaker_name, project_id)

    # Build the instruction + beep audio
    instruction_text = get_enrollment_instruction_text(speaker_name)

    provider = await get_tts_provider(db, project_id=project_id or None)
    plugin = plugin_manager.get_channel(channel_id)

    if provider and plugin and hasattr(plugin, "_play_prompt"):
        try:
            # Synthesize instruction
            instruction_audio = await provider.synthesize(instruction_text, voice="alloy", speed=1.0)

            # Generate beep tone
            beep_audio = generate_beep(frequency=880, duration_sec=0.5)

            # Concatenate: instruction + short pause + beep
            # Both should be WAV — we'll play them sequentially via two playPrompt calls
            # First: play instruction
            instr_file_id = str(uuid.uuid4())
            _temp_audio[instr_file_id] = instruction_audio
            instr_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{instr_file_id}"
            await plugin._play_prompt(call_id, instr_url)

            # Brief pause then beep
            await asyncio.sleep(1.5)
            beep_file_id = str(uuid.uuid4())
            _temp_audio[beep_file_id] = beep_audio
            beep_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{beep_file_id}"
            await plugin._play_prompt(call_id, beep_url)

            print(f"[CALL DEBUG] Enrollment instruction + beep played for {call_id}", file=_sys.stderr, flush=True)
        except Exception as _err:
            print(
                f"[CALL DEBUG] Enrollment TTS/beep failed: error_type={type(_err).__name__}",
                file=_sys.stderr,
                flush=True,
            )
            logger.exception("Enrollment flow TTS failed for call %s", call_id)

    # Start a longer recording for the voice sample (15s, relaxed silence)
    await asyncio.sleep(1.0)  # Give time for beep to finish playing
    if plugin and hasattr(plugin, "_start_record"):
        await plugin._start_record(
            call_id,
            max_duration=15,  # 15 seconds of recording
            initial_silence=10,  # Wait up to 10s for them to start talking
            max_silence=8,  # Allow 8s silence (they might pause between sentences)
        )
        print(f"[CALL DEBUG] Enrollment recording started for {call_id} (15s)", file=_sys.stderr, flush=True)


async def handle_enrollment_sample(
    call_id: str,
    channel_id: str,
    project_id: str,
    speaker_name: str,
    audio_bytes: bytes,
    https_base: str,
    db: AsyncSession,
) -> None:
    """Process the voice enrollment sample: extract embedding and enroll the speaker.

    Called when a recording completes and there's an active enrollment session.
    """
    import sys as _sys

    from ...plugins import plugin_manager
    from ...services.speaker.diarization import enroll_speaker
    from ...services.speaker.voice_enrollment import (
        complete_enrollment,
        generate_beep,
        get_enrollment_failure_text,
        get_enrollment_success_text,
    )

    print(
        f"[CALL DEBUG] Processing enrollment sample for {person_log_ref(speaker_name)} ({len(audio_bytes)} bytes)",
        file=_sys.stderr,
        flush=True,
    )

    # Check minimum audio size — enrollment needs at least ~3 seconds of 16kHz 16-bit mono
    # = 3 * 16000 * 2 = 96000 bytes of raw audio, plus WAV header ≈ ~50KB minimum WAV file
    if len(audio_bytes) < 30000:
        print(
            f"[CALL DEBUG] Enrollment sample too small ({len(audio_bytes)} bytes) — ignoring, waiting for real sample",
            file=_sys.stderr,
            flush=True,
        )
        # Don't complete enrollment — keep session active for the real recording
        return

    # Complete/remove the enrollment session
    complete_enrollment(call_id)

    plugin = plugin_manager.get_channel(channel_id)
    provider = await get_tts_provider(db, project_id=project_id or None)

    # Set playback lock to suppress recording during enrollment TTS
    _playback_locks[call_id] = asyncio.Event()

    # Play end beep
    if plugin and hasattr(plugin, "_play_prompt"):
        beep_audio = generate_beep(frequency=660, duration_sec=0.3)
        beep_file_id = str(uuid.uuid4())
        _temp_audio[beep_file_id] = beep_audio
        beep_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{beep_file_id}"
        try:
            await plugin._play_prompt(call_id, beep_url)
        except Exception:
            pass

    # Try to enroll the speaker
    try:
        profile = enroll_speaker(
            name=speaker_name,
            audio_bytes=audio_bytes,
            project_id=project_id,
        )
        print(
            f"[CALL DEBUG] Enrollment SUCCESS: {person_log_ref(speaker_name)}, embedding_dim={len(profile.embedding)}",
            file=_sys.stderr,
            flush=True,
        )
        logger.info("Voice enrollment successful for %s (project %s)", person_log_ref(speaker_name), project_id)

        # Play success confirmation
        success_text = get_enrollment_success_text(speaker_name)
        if provider and plugin and hasattr(plugin, "_play_prompt"):
            try:
                success_audio = await provider.synthesize(success_text, voice="alloy", speed=1.0)
                file_id = str(uuid.uuid4())
                _temp_audio[file_id] = success_audio
                audio_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"
                # Wait for beep to finish, then play success
                await asyncio.sleep(0.5)
                await plugin._play_prompt(call_id, audio_url)
                # Wait for the full success message to play before restarting recording
                playback_duration = estimate_wav_duration(success_audio)
                wait_time = playback_duration + 1.5
                print(
                    f"[CALL DEBUG] Enrollment success: waiting {wait_time:.1f}s for TTS playback",
                    file=_sys.stderr,
                    flush=True,
                )
                await asyncio.sleep(wait_time)
            except Exception as _err:
                print(
                    f"[CALL DEBUG] Enrollment success TTS failed: error_type={type(_err).__name__}",
                    file=_sys.stderr,
                    flush=True,
                )

    except Exception as _enroll_err:
        print(
            f"[CALL DEBUG] Enrollment FAILED for {person_log_ref(speaker_name)}: error_type={type(_enroll_err).__name__}",
            file=_sys.stderr,
            flush=True,
        )
        logger.exception("Voice enrollment failed for %s", person_log_ref(speaker_name))

        # Play failure message
        failure_text = get_enrollment_failure_text(speaker_name)
        if provider and plugin and hasattr(plugin, "_play_prompt"):
            try:
                failure_audio = await provider.synthesize(failure_text, voice="alloy", speed=1.0)
                file_id = str(uuid.uuid4())
                _temp_audio[file_id] = failure_audio
                audio_url = f"{https_base}/api/v1/teams/calls/{call_id}/audio/temp/{file_id}"
                await asyncio.sleep(0.5)
                await plugin._play_prompt(call_id, audio_url)
                # Wait for failure message to finish too
                playback_duration = estimate_wav_duration(failure_audio)
                await asyncio.sleep(playback_duration + 1.5)
            except Exception:
                pass

    # Release playback lock and resume normal recording
    _playback_locks.pop(call_id, None)
    await restart_recording(call_id, channel_id)
