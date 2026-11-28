# ruff: noqa: E501
"""In-memory state for active Teams calls and its database persistence."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import async_session_factory
from ...models import Message, Session
from ...time_utils import utc_now

logger = logging.getLogger(__name__)

# --- Temp audio store (file_id -> audio bytes) served via the route ---
_temp_audio: dict[str, bytes] = {}

# --- Playback state: suppress recording restart while bot is speaking ---
# Maps call_id -> asyncio.Event that is SET when the bot finishes speaking
# and it's safe to start recording again.
_playback_locks: dict[str, asyncio.Event] = {}


def get_temp_audio(file_id: str) -> bytes | None:
    return _temp_audio.get(file_id)


def is_bot_speaking(call_id: str) -> bool:
    return call_id in _playback_locks


def signal_playback_done(call_id: str) -> None:
    evt = _playback_locks.get(call_id)
    if evt and not evt.is_set():
        evt.set()


# --- Rolling Transcript Store ---


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    speaker_label: str  # "SPEAKER_00", "SPEAKER_01", "BOT", etc.
    text: str
    speaker_name: str | None = None  # Resolved name from diarization enrollment
    speaker_source: str = ""  # "diarization", "teams_api", "bot", or ""
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class CallSessionState:
    call_id: str
    project_id: str | None
    channel_id: str | None
    started_at: datetime
    segments: list[TranscriptSegment] = field(default_factory=list)
    audio_ms_offset: int = 0  # Running audio timestamp offset
    db_session_id: str | None = None  # chat session linked to this call

    @property
    def transcript_text(self) -> str:
        if not self.segments:
            return ""
        lines = []
        for seg in self.segments:
            time_str = f"[{seg.start_ms // 60000:02d}:{(seg.start_ms % 60000) // 1000:02d}]"
            speaker = seg.speaker_name or seg.speaker_label
            lines.append(f"{time_str} {speaker}: {seg.text}")
        return "\n".join(lines)

    def add_user_segment(
        self, text: str, duration_ms: int, speaker_name: str | None = None, speaker_source: str = ""
    ) -> None:
        self.segments.append(
            TranscriptSegment(
                start_ms=self.audio_ms_offset,
                end_ms=self.audio_ms_offset + duration_ms,
                speaker_label=speaker_name or "Participant",
                text=text,
                speaker_name=speaker_name,
                speaker_source=speaker_source,
            )
        )
        self.audio_ms_offset += duration_ms

    def add_bot_segment(self, text: str) -> None:
        if self.segments:
            last_end = self.segments[-1].end_ms
        else:
            last_end = self.audio_ms_offset
        self.segments.append(
            TranscriptSegment(
                start_ms=last_end,
                end_ms=last_end,
                speaker_label="BOT",
                text=text,
            )
        )


# In-memory store for active calls
_call_states: dict[str, CallSessionState] = {}


def get_call_state(call_id: str) -> CallSessionState:
    if call_id not in _call_states:
        _call_states[call_id] = CallSessionState(
            call_id=call_id,
            project_id=None,
            channel_id=None,
            started_at=utc_now(),
        )
    return _call_states[call_id]


def cleanup_call_state(call_id: str) -> CallSessionState | None:
    return _call_states.pop(call_id, None)


@dataclass(frozen=True, slots=True)
class CallDbSession:
    session_id: str | None
    state: str | None = None


async def ensure_call_db_session(
    call_id: str,
    project_id: str,
    channel_id: str,
    db: AsyncSession,
    *,
    caller_id: str | None,
) -> CallDbSession:
    state = get_call_state(call_id)
    if state.db_session_id:
        return CallDbSession(state.db_session_id)

    from .call_owner import resolve_call_owner

    owner = await resolve_call_owner(db, channel_id=channel_id, project_id=project_id or None, caller_id=caller_id)
    if owner.user_id is None:
        logger.warning("Teams call session refused: call_id=%s state=%s", call_id, owner.state)
        return CallDbSession(None, owner.state)

    session = Session(
        id=str(uuid.uuid4()),
        user_id=owner.user_id,
        project_id=project_id or None,
        agent_type="teams_call",
        status="active",
        origin="channel",
        metadata_={
            "call_id": call_id,
            "channel_id": channel_id,
            "source": "teams_calling",
        },
    )
    db.add(session)
    await db.flush()

    state.db_session_id = session.id
    logger.info("Created chat session %s for call %s", session.id, call_id)
    return CallDbSession(session.id)


async def add_call_message(
    session_id: str,
    role: str,
    content: str,
    db: AsyncSession,
) -> None:
    msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
    )
    db.add(msg)
    await db.flush()


async def close_call_db_session(call_id: str, error: str | None = None) -> None:
    import sys as _sys

    state = _call_states.get(call_id)
    if not state or not state.db_session_id:
        # Still cleanup state even if no session
        _call_states.pop(call_id, None)
        return

    transcript = state.transcript_text
    channel_id = state.channel_id
    project_id = state.project_id
    db_session_id = state.db_session_id

    async with async_session_factory() as db:
        # Generate meeting summary if there's meaningful transcript
        if transcript and len(state.segments) >= 2:
            print(
                f"[CALL DEBUG] Generating meeting summary for {call_id} ({len(state.segments)} segments)",
                file=_sys.stderr,
                flush=True,
            )
            try:
                from .agent_orchestration import generate_meeting_summary

                summary = await generate_meeting_summary(transcript, channel_id, project_id, db)
                if summary:
                    await add_call_message(db_session_id, "assistant", summary, db)
                    print(
                        f"[CALL DEBUG] Meeting summary saved for {call_id}: chars={len(summary)}",
                        file=_sys.stderr,
                        flush=True,
                    )
            except Exception as _sum_err:
                print(
                    f"[CALL DEBUG] Meeting summary generation failed: error_type={type(_sum_err).__name__}",
                    file=_sys.stderr,
                    flush=True,
                )
                logger.exception("Meeting summary failed for call %s", call_id)

        result = await db.execute(select(Session).where(Session.id == db_session_id))
        session = result.scalar_one_or_none()
        if session:
            from ...time_utils import utc_now as _utc_now

            session.status = "failed" if error else "completed"
            session.ended_at = _utc_now()
            meta = dict(session.metadata_ or {})
            if error:
                meta["last_error"] = error[:500]
            meta["transcript_segments"] = len(state.segments)
            meta["transcript_duration_ms"] = state.audio_ms_offset
            # Persist full segment data so transcript is available after call ends
            meta["segments_data"] = [
                {
                    "start_ms": seg.start_ms,
                    "end_ms": seg.end_ms,
                    "speaker": seg.speaker_name or seg.speaker_label or "Unknown",
                    "speaker_source": seg.speaker_source if hasattr(seg, "speaker_source") else "",
                    "text": seg.text,
                    "timestamp": seg.timestamp.isoformat() if hasattr(seg, "timestamp") and seg.timestamp else None,
                }
                for seg in state.segments
            ]
            meta["transcript_text"] = transcript
            meta["caller_display_name"] = getattr(state, "caller_display_name", None)
            session.metadata_ = meta
            await db.commit()

    # Cleanup call state after everything is persisted
    _call_states.pop(call_id, None)
