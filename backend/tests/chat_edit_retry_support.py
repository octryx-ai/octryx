"""Session and message builders plus the stale later-turn state seeds for the test_chat_edit_retry* modules."""

import json
import uuid
from datetime import timedelta

from app.models import (
    Approval,
    ChangePreview,
    ContextCheckpoint,
    Message,
    PrefetchCacheEntry,
    Session,
    SessionEntity,
    SessionToolCacheEntry,
    ThreadContext,
    ToolArtifact,
    ToolCall,
    ToolResultCompressionLog,
    TurnTrace,
    UsageEvent,
)


def _rerun_session(user_id, *, title, status="active", project_id=None) -> Session:
    return Session(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_id=project_id,
        agent_type="diagnosis",
        status=status,
        metadata_={"title": title, "thinking_level": "light", "runtime_target_id": ""},
    )


def _messages(session_id, base_time, turns) -> list[Message]:
    """One message per (role, content, seconds after base_time) turn."""
    return [
        Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            created_at=base_time + timedelta(seconds=offset),
        )
        for role, content, offset in turns
    ]


def _seed_stale_tool_rows(db, session_id, user_id, message_id, base_time) -> None:
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session_id,
        message_id=message_id,
        tool_name="search_confluence",
        parameters={"query": "report-builder"},
        result={"items": [{"title": "Stale"}]},
        created_at=base_time + timedelta(seconds=21),
    )
    db.add(tool_call)
    db.add(
        ToolArtifact(
            id=tool_call.id,
            session_id=session_id,
            message_id=message_id,
            tool_name="search_confluence",
            storage_backend="disk_json_gzip",
            relative_path=f"tests/{uuid.uuid4().hex}.json.gz",
            content_sha256="abc123",
            payload_size_bytes=12,
            is_compressed=True,
            preview_json={"items": 1},
            created_at=base_time + timedelta(seconds=21),
        )
    )
    db.add(
        TurnTrace(
            id=str(uuid.uuid4()),
            session_id=session_id,
            message_id=message_id,
            provider="test",
            model="stub-model",
            created_at=base_time + timedelta(seconds=22),
        )
    )
    db.add(
        UsageEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            provider="test",
            model="stub-model",
            tokens_in=111,
            tokens_out=222,
            created_at=base_time + timedelta(seconds=23),
        )
    )


async def _seed_stale_approval(db, session_id, user_id, message_id, base_time) -> Approval:
    approval = Approval(
        id=str(uuid.uuid4()),
        session_id=session_id,
        requested_by=user_id,
        action="Run command",
        status="pending",
        created_at=base_time + timedelta(seconds=24),
    )
    db.add(approval)
    await db.flush()
    db.add(
        ChangePreview(
            id=str(uuid.uuid4()),
            session_id=session_id,
            approval_id=approval.id,
            tool_name="bash",
            preview_json=json.dumps({"summary": "stale preview"}),
            request_fingerprint="stale-preview",
            created_at=base_time + timedelta(seconds=25),
        )
    )
    db.add(
        ThreadContext(
            id=str(uuid.uuid4()),
            session_id=session_id,
            context_json={"status": "stale"},
            derived_from_message_id=message_id,
        )
    )
    return approval


def _seed_stale_caches(db, session_id, base_time) -> None:
    db.add(
        SessionToolCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name="search_confluence",
            params_hash="stale-cache",
            result_json={"cached": True},
            ttl_seconds=60,
            cached_at=base_time + timedelta(seconds=28),
        )
    )
    db.add(
        PrefetchCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name="search_confluence",
            params_hash="prefetch",
            params_json={"query": "report-builder"},
            result_json={"cached": True},
            created_at=base_time + timedelta(seconds=29),
        )
    )
    db.add(
        ContextCheckpoint(
            id=str(uuid.uuid4()),
            session_id=session_id,
            checkpoint_name="stale-checkpoint",
            context_snapshot_json={"foo": "bar"},
            created_at=base_time + timedelta(seconds=30),
        )
    )


def _seed_stale_entities_and_compression(db, session_id, first_seen_message_id, message_id, base_time) -> None:
    db.add(
        SessionEntity(
            id=str(uuid.uuid4()),
            session_id=session_id,
            entity_type="tool",
            entity_id="report-builder",
            label="report-builder",
            state_json={"status": "stale"},
            first_seen_message_id=first_seen_message_id,
            last_updated_message_id=message_id,
            created_at=base_time + timedelta(seconds=31),
        )
    )
    db.add(
        ToolResultCompressionLog(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name="search_confluence",
            strategy="fallback",
            original_tokens=1000,
            compressed_tokens=200,
            compression_ratio=80,
            created_at=base_time + timedelta(seconds=32),
        )
    )
