"""WebSocket endpoint for Teams call audio bridging.

The .NET MediaBridge connects here per call:
  - Sends raw PCM (16kHz, 16-bit, mono) chunks from the Teams audio stream.
  - Receives raw PCM chunks (16kHz, 16-bit, mono) to inject as bot speech.

Pipeline per utterance:
  PCM chunks → VAD silence detection → WAV wrap → STT → agent turn → TTS → PCM → MediaBridge

This module is transport only. The business logic lives in
``app.services.teams_calling`` (recording processor, audio pipeline, call
session state, channel context, agent orchestration, enrollment flow).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services.access_control import require_existing_workspace
from ...services.channel_webhook_auth import STATE_SIGNATURE_INVALID, STATE_UNAUTHENTICATED
from ...services.stt import get_stt_service
from ...services.teams_calling import call_session_state
from ...services.teams_calling.agent_orchestration import agent_response
from ...services.teams_calling.audio import DEFAULT_PCM_FORMAT, SpeechBuffer, pcm_rms, pcm_to_wav
from ...services.teams_calling.audio_pipeline import (
    ENERGY_THRESHOLD,
    MAX_AUDIO_CHUNK_BYTES,
    SILENCE_FLUSH_MS,
    tts_to_pcm,
)
from ...services.teams_calling.audio_ws_token import (
    STATE_TOKEN_MISSING,
    consume_call_audio_token,
    verify_call_audio_token,
)
from ...services.teams_calling.channel_context import (
    get_channel_calling_config,
    get_channel_calling_context,
)
from ...services.teams_calling.wake_word import WakeWordPolicy

router = APIRouter(prefix="/api/v1/teams/calls", tags=["teams-calling"])
logger = logging.getLogger(__name__)


class _CallAudioBridge:
    """One call's audio: buffers speech and sends each utterance through STT, the agent and TTS back to the call."""

    def __init__(self, ws: WebSocket, db: AsyncSession, *, call_id: str, call_state, wake_word_policy: WakeWordPolicy,
                 project_id: str, channel_id: str) -> None:
        self.ws = ws
        self.db = db
        self.call_id = call_id
        self.call_state = call_state
        self.wake_word_policy = wake_word_policy
        self.project_id = project_id
        self.channel_id = channel_id
        self.speech_buffer = SpeechBuffer(
            audio_format=DEFAULT_PCM_FORMAT,
            silence_flush_ms=SILENCE_FLUSH_MS,
            energy_threshold=ENERGY_THRESHOLD,
        )
        self.flush_lock = asyncio.Lock()
        self.flush_task: asyncio.Task | None = None

    async def flush_and_respond(self) -> None:
        async with self.flush_lock:
            if not self.speech_buffer.has_speech:
                return
            pcm = self.speech_buffer.take()

        stt = await get_stt_service(self.db)
        if stt is None:
            logger.warning("STT service not available for call %s", self.call_id)
            return

        try:
            chunk_duration_ms = DEFAULT_PCM_FORMAT.duration_ms(pcm)
            wav = pcm_to_wav(pcm)
            text = await stt.transcribe(wav, filename="audio.wav")
            text = text.strip()
            if not text:
                return
            logger.info("Call %s STT: chars=%d", self.call_id, len(text))

            # Add user segment to transcript
            self.call_state.add_user_segment(text, duration_ms=chunk_duration_ms)

            wake_word_decision = self.wake_word_policy.evaluate(text)
            if not wake_word_decision.should_respond:
                logger.debug("Call %s transcript segment did not match wake word", self.call_id)
                return

            response = await agent_response(
                text=wake_word_decision.command_text,
                call_id=self.call_id,
                channel_id=self.channel_id,
                db=self.db,
                project_id=self.project_id or None,
            )
            if not response:
                return

            # Add bot segment to transcript
            self.call_state.add_bot_segment(response)

            audio = await tts_to_pcm(response, self.db, project_id=self.project_id or None)
            if audio:
                await self.ws.send_bytes(audio)
        except Exception:
            logger.exception("Error processing audio for call %s", self.call_id)

    async def schedule_flush(self) -> None:
        self.cancel_pending_flush()
        self.flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(SILENCE_FLUSH_MS / 1000)
        await self.flush_and_respond()

    def cancel_pending_flush(self) -> None:
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()

    async def pump(self) -> None:
        """Read audio until the call ends; an oversized chunk closes the WebSocket."""
        while True:
            chunk = await self.ws.receive_bytes()
            if len(chunk) > MAX_AUDIO_CHUNK_BYTES:
                logger.warning(
                    "Closing Teams call %s WebSocket after oversized audio chunk: %d bytes",
                    self.call_id,
                    len(chunk),
                )
                await self.ws.close(code=1009, reason="Audio chunk too large")
                return
            is_speech = pcm_rms(chunk) >= ENERGY_THRESHOLD
            should_flush = self.speech_buffer.add_chunk(chunk)
            if should_flush:
                await self.flush_and_respond()
                self.cancel_pending_flush()
            elif is_speech:
                await self.schedule_flush()


@router.websocket("/{call_id}/audio/ws")
async def call_audio_ws(
    call_id: str,
    ws: WebSocket,
    project_id: str = "",
    channel_id: str = "",
    token: str = "",
    db: AsyncSession = Depends(get_db),
) -> None:
    # The per-call, single-use token the platform issued when it accepted this call; refused
    # before the WebSocket is accepted, so no audio is read (``audio_ws_token.py``).
    refusal = consume_call_audio_token(call_id, channel_id=channel_id, token=token)
    if refusal is not None:
        logger.info("Teams call audio WebSocket refused: call_id=%s reason=%s", call_id, refusal)
        await ws.close(code=1008, reason=refusal)
        return
    try:
        context = await get_channel_calling_context(
            db,
            channel_id=channel_id,
            project_id=project_id or None,
        )
    except HTTPException as exc:
        await ws.close(code=1008, reason=str(exc.detail)[:120])
        return

    project_id = context.project_id
    channel_id = context.channel_id
    wake_word_policy = WakeWordPolicy.from_config(context.config)

    await ws.accept()
    logger.info(
        "Teams call audio WebSocket connected: call_id=%s project=%s channel=%s",
        call_id,
        project_id,
        channel_id,
    )

    # Initialize call state
    call_state = call_session_state.get_call_state(call_id)
    call_state.project_id = project_id
    call_state.channel_id = channel_id
    bridge = _CallAudioBridge(ws, db, call_id=call_id, call_state=call_state, wake_word_policy=wake_word_policy,
                              project_id=project_id, channel_id=channel_id)

    try:
        await bridge.pump()
    except WebSocketDisconnect:
        logger.info("Teams call audio WebSocket disconnected: call_id=%s", call_id)
    finally:
        bridge.cancel_pending_flush()
        # Cleanup call state
        state = call_session_state.cleanup_call_state(call_id)
        if state:
            logger.info(
                "Call %s transcript: %d segments, duration: %dms",
                call_id,
                len(state.segments),
                state.audio_ms_offset,
            )


# --- Incoming Call Webhook (called by the call proxy) ---


@router.post("/incoming-call")
async def incoming_call_webhook(
    call_id: str = Query(...),
    channel_id: str = Query(...),
    project_id: str = Query(...),
    audio_token: str = Query(""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Called by the call proxy when an incoming Teams call is received.
    Returns the caller's info and webhook URL for the MediaBridge to connect to.
    ``audio_token`` is the call's audio WebSocket token the platform issued when it redirected
    the call. It authenticates this callback: without the call's valid,
    unexpired, unused token for this channel the callback is refused before anything is read
    (``channel_webhook_unauthenticated`` / ``channel_webhook_signature_invalid``). It is only
    checked here, not consumed; the WebSocket consumes it.

    The MediaBridge connects here via WebSocket to stream audio and receive responses.
    For local dev: use ngrok tunnel URL (e.g. wss://xxx.ngrok-free.dev).
    For EKS: use the cluster's public domain or a per-channel configured URL.
    """
    refusal = verify_call_audio_token(call_id, channel_id=channel_id, token=audio_token)
    if refusal is not None:
        state = STATE_UNAUTHENTICATED if refusal == STATE_TOKEN_MISSING else STATE_SIGNATURE_INVALID
        logger.info("Teams incoming-call callback refused: call_id=%s state=%s", call_id, state)
        raise HTTPException(status_code=401, detail={"code": state})
    await require_existing_workspace(db, project_id)
    channel_config = await get_channel_calling_config(db, channel_id)

    webhook_url = channel_config.get("calling_webhook_url", "")
    thinking_message = channel_config.get("call_agent_thinking_message", "One moment please.")

    # Public WebSocket URL: use channel-specific setting if configured,
    # otherwise derive from calling_webhook_url (the call proxy's base URL)
    public_ws_url = channel_config.get("calling_public_ws_url", "").strip()
    if not public_ws_url and webhook_url:
        # Strip path and use wss://
        from urllib.parse import urlparse

        parsed = urlparse(webhook_url)
        if parsed.scheme in ("http", "https"):
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            public_ws_url = f"{ws_scheme}://{parsed.netloc}"
        else:
            public_ws_url = "ws://localhost:8000"

    query = urlencode({"project_id": project_id, "channel_id": channel_id, "token": audio_token})
    audio_ws_url = f"{public_ws_url}/api/v1/teams/calls/{quote(call_id, safe='')}/audio/ws?{query}"

    return {
        "status": "ready",
        "call_id": call_id,
        "audioWebSocketUri": audio_ws_url,
        "audio_ws_url": audio_ws_url,
        "thinking_message": thinking_message,
        "webhook_url": webhook_url,
    }


@router.get("/{call_id}/audio/temp/{file_id}")
async def get_temp_audio(call_id: str, file_id: str) -> Response:
    """Serve a TTS audio blob for Graph API playPrompt."""
    audio = call_session_state.get_temp_audio(file_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    media_type = "audio/mpeg" if audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb" else "audio/wav"
    return Response(content=audio, media_type=media_type)
