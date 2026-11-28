"""Payload builders for the call monitoring panel: live in-memory call state and the events of one call."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _active_calls_info(plugin_manager: Any) -> dict[str, dict]:
    active_calls_info = {}
    try:
        for ch_id, plugin in plugin_manager._channels.items():
            if hasattr(plugin, "_active_calls"):
                for call_id, call_info in plugin._active_calls.items():
                    active_calls_info[call_id] = {
                        **call_info,
                        "channel_instance_id": ch_id,
                    }
    except Exception:
        pass
    return active_calls_info


def _live_segments(state: Any) -> list[dict]:
    segments = []
    for seg in state.segments:
        segments.append(
            {
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "speaker": seg.speaker_name or seg.speaker_label,
                "speaker_source": seg.speaker_source if hasattr(seg, "speaker_source") else "",
                "text": seg.text,
                "timestamp": seg.timestamp.isoformat() if hasattr(seg, "timestamp") else None,
            }
        )
    return segments


def _enrollment(call_id: str, enrollment_sessions: dict) -> dict | None:
    if call_id not in enrollment_sessions:
        return None
    es = enrollment_sessions[call_id]
    return {
        "speaker_name": es.speaker_name,
        "state": es.state.name,
        "project_id": es.project_id,
    }


def _tracked_call(
    call_id: str,
    state: Any,
    active_calls_info: dict[str, dict],
    enrollment_sessions: dict,
    playback_locks: Any,
) -> dict:
    call_plugin_info = active_calls_info.get(call_id, {})
    segments = _live_segments(state)
    return {
        "call_id": call_id,
        "project_id": state.project_id,
        "channel_id": state.channel_id,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "duration_ms": state.audio_ms_offset,
        "db_session_id": state.db_session_id,
        "segments": segments,
        "segment_count": len(segments),
        "is_bot_speaking": call_id in playback_locks,
        "enrollment": _enrollment(call_id, enrollment_sessions),
        "caller_display_name": call_plugin_info.get("caller_display_name", ""),
        "caller_id": call_plugin_info.get("caller_id", ""),
        "is_direct_call": call_plugin_info.get("is_direct_call", False),
        "is_graph_active": call_id in active_calls_info,
    }


def _untracked_call(call_id: str, info: dict, playback_locks: Any) -> dict:
    return {
        "call_id": call_id,
        "project_id": info.get("project_id", ""),
        "channel_id": info.get("channel_id", ""),
        "started_at": None,
        "duration_ms": 0,
        "db_session_id": None,
        "segments": [],
        "segment_count": 0,
        "is_bot_speaking": call_id in playback_locks,
        "enrollment": None,
        "caller_display_name": info.get("caller_display_name", ""),
        "caller_id": info.get("caller_id", ""),
        "is_direct_call": info.get("is_direct_call", False),
        "is_graph_active": True,
    }


def _enrolled_speakers() -> dict[str, dict]:
    enrolled_speakers = {}
    try:
        from ...services.speaker.diarization import _speaker_profiles

        for project_id, profiles in _speaker_profiles.items():
            for profile in profiles:
                key = f"{project_id}:{profile.name}"
                enrolled_speakers[key] = {
                    "name": profile.name,
                    "project_id": project_id,
                    "enrolled_at": profile.enrolled_at,
                    "embedding_dim": len(profile.embedding) if profile.embedding is not None else 0,
                }
    except (ImportError, Exception):
        pass
    return enrolled_speakers


def build_live_calls_payload() -> dict[str, Any]:
    from ...plugins import plugin_manager
    from ...services.speaker.voice_enrollment import (
        _enrollment_sessions,
    )
    from ...services.teams_calling.call_session_state import (
        _call_states,
        _playback_locks,
        _temp_audio,
    )
    from ...services.teams_calling.recording_processor import _recording_queue

    active_calls_info = _active_calls_info(plugin_manager)
    calls = [
        _tracked_call(call_id, state, active_calls_info, _enrollment_sessions, _playback_locks)
        for call_id, state in _call_states.items()
    ]
    calls.extend(
        _untracked_call(call_id, info, _playback_locks)
        for call_id, info in active_calls_info.items()
        if call_id not in _call_states
    )
    enrolled_speakers = _enrolled_speakers()
    return {
        "calls": sorted(calls, key=lambda c: c.get("started_at") or "", reverse=True),
        "stats": {
            "active_calls": len(active_calls_info),
            "tracked_sessions": len(_call_states),
            "recording_queue_size": _recording_queue.qsize(),
            "temp_audio_files": len(_temp_audio),
            "active_enrollments": len(_enrollment_sessions),
            "enrolled_speakers": len(enrolled_speakers),
        },
        "enrolled_speakers": enrolled_speakers,
    }


def _event_segments(state: Any) -> list[dict]:
    segments = []
    for seg in state.segments:
        segments.append(
            {
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "speaker": seg.speaker_name or seg.speaker_label or "Unknown",
                "speaker_source": seg.speaker_source if hasattr(seg, "speaker_source") else "",
                "text": seg.text,
                "timestamp": seg.timestamp.isoformat() if hasattr(seg, "timestamp") and seg.timestamp else None,
            }
        )
    return segments


async def _session_messages(db: AsyncSession, session_id: str) -> list[dict]:
    from ...models import Message

    messages = []
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    for msg in result.scalars().all():
        messages.append(
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content[:500] if msg.content else "",
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
        )
    return messages


async def _ended_call_events(db: AsyncSession, call_id: str) -> dict[str, Any]:
    from ...models import Session

    result = await db.execute(
        select(Session)
        .where(Session.agent_type == "teams_call")
        .where(func.json_extract(Session.metadata_, "$.call_id") == call_id)
        .order_by(Session.started_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"messages": [], "transcript": "", "segments": []}

    meta = dict(session.metadata_ or {})
    return {
        "messages": await _session_messages(db, session.id),
        "transcript": meta.get("transcript_text", ""),
        "segments": meta.get("segments_data", []),
    }


async def build_call_events_payload(db: AsyncSession, call_id: str) -> dict[str, Any]:
    from ...services.teams_calling.call_session_state import _call_states

    state = _call_states.get(call_id)
    if not state:
        return await _ended_call_events(db, call_id)
    segments = _event_segments(state)
    messages = await _session_messages(db, state.db_session_id) if state.db_session_id else []
    return {
        "messages": messages,
        "transcript": state.transcript_text,
        "segments": segments,
    }
