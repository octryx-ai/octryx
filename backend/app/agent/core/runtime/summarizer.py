"""Rolling session summarizer.

After each agent turn, if the session history exceeds SUMMARIZE_THRESHOLD messages,
the older messages are compressed into a compact summary stored in
session.metadata_["summary"].  The engine then sends only:

    [system prompt]
    [<session_summary> block]   ← injected when summary exists
    [last WINDOW_SIZE messages]  ← always in full
    [current user message]

This keeps the context window lean (~6-8k tokens) regardless of session length.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.prompt_catalog import render_prompt
from ._summarizer_evidence import (
    collect_evidence_from_messages as _collect_evidence_from_messages,
)
from ._summarizer_evidence import render_evidence_prompt_block
from .summary_structure import (
    apply_reference_markers,
    clean_summary_text,
    parse_existing_summary_json,
    parse_summary_response,
    render_messages,
    render_structured_summary,
)

# How many recent messages to always send verbatim.
WINDOW_SIZE = 8
# Start summarising once a session exceeds this many messages.
SUMMARIZE_THRESHOLD = 10

# The strict output schema the summary parser (``parse_summary_response``) depends on: a fixed
# protocol string, so it stays in code and fills ``{output_schema}`` of ``context.summarizer.user``.
SUMMARY_OUTPUT_SCHEMA = (
    "{\n"
    '  "goal": "string",\n'
    '  "findings": [{"type": "string", "text": "string", "entities": ["optional"]}],\n'
    '  "actions_taken": [{"tool": "string", "action": "string", "result": "string"}],\n'
    '  "open_items": ["string"],\n'
    '  "state": "in_progress|blocked|completed|unknown"\n'
    "}\n"
)


def build_summary_user_prompt(*, existing_summary: str, messages_text: str, evidence_block: str) -> str:
    existing_block = (
        render_prompt("context.summarizer.existing_summary_block", existing_summary=existing_summary)
        if existing_summary
        else ""
    )
    return render_prompt(
        "context.summarizer.user",
        existing_summary_block=existing_block,
        messages_text=messages_text,
        evidence_block=evidence_block,
        output_schema=SUMMARY_OUTPUT_SCHEMA,
    )


async def maybe_update_summary(session_id: str, db: AsyncSession) -> None:
    """Update the rolling summary for a session if it's grown past the threshold.

    Called after each agent turn. Silently skips on error so it never
    breaks the main conversation flow.
    """
    try:
        await _update_summary(session_id, db)
    except Exception:
        pass  # Never let summarisation errors surface to users


async def _load_summary_session(db: AsyncSession, session_id: str) -> tuple[Any, list] | None:
    """The session and its summarisable messages; ``None`` when there is no session."""
    from ....models.session import Message, Session  # local import to avoid circular
    from ..context.runtime_readiness_history import exclude_runtime_readiness_blocked_turns

    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        return None

    # Load all messages; runtime-readiness-blocked turns never ran and are not summarised
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    all_messages = await exclude_runtime_readiness_blocked_turns(
        db, session_id=session_id, messages=result.scalars().all()
    )
    return session, all_messages


def _messages_to_summarise(all_messages: list, metadata: dict) -> tuple[list, str] | None:
    """The messages older than the sliding window and the last one's id; ``None`` when nothing new is due."""
    if len(all_messages) <= SUMMARIZE_THRESHOLD:
        return None  # Not enough messages yet
    last_summarised_count: int = metadata.get("summary_message_count", 0)
    # Only messages older than the sliding window need summarising
    messages_to_summarise = all_messages[: max(0, len(all_messages) - WINDOW_SIZE)]
    # Skip if nothing new to summarise since last run
    if len(messages_to_summarise) <= last_summarised_count:
        return None
    # Cooldown: skip when the source window still ends at the same message.
    source_last_message_id = str(getattr(messages_to_summarise[-1], "id", "") or "")
    if source_last_message_id and source_last_message_id == str(metadata.get("summary_source_last_message_id") or ""):
        return None
    return messages_to_summarise, source_last_message_id


def _first_user_goal(all_messages: list) -> str:
    return clean_summary_text(
        next(
            (message.content for message in all_messages if getattr(message, "role", "") == "user" and message.content),
            "",
        ),
        limit=220,
    )


async def _update_summary(session_id: str, db: AsyncSession) -> None:
    from ....services.content_security.model_call_scope import model_call_scope, session_call
    from ...providers import get_provider
    from ._summarizer_runtime import resolve_summarizer_runtime

    loaded = await _load_summary_session(db, session_id)
    if loaded is None:
        return
    session, all_messages = loaded
    metadata = dict(session.metadata_ or {})
    existing_summary: str = metadata.get("summary", "")
    existing_summary_json = parse_existing_summary_json(existing_summary, metadata)
    due = _messages_to_summarise(all_messages, metadata)
    if due is None:
        return
    messages_to_summarise, source_last_message_id = due
    new_messages = messages_to_summarise[metadata.get("summary_message_count", 0):]
    evidence_refs = _collect_evidence_from_messages(new_messages)
    user_prompt = build_summary_user_prompt(
        existing_summary=existing_summary or "",
        messages_text=render_messages(new_messages),
        evidence_block=render_evidence_prompt_block(evidence_refs),
    )
    # Prefer a runtime target an operator tagged for summarization; otherwise the
    # first runtime of the platform order. Either way the session's own project — never
    # a caller argument — decides admission, and a refusal is recorded on the
    # session so an operator sees a summary missing by policy, not by failure.
    summary_runtime = await resolve_summarizer_runtime(db, project_id=getattr(session, "project_id", None))
    if not summary_runtime.admitted:
        session.metadata_ = {**metadata, "summary_admission": summary_runtime.denial}
        await db.commit()
        return
    provider = get_provider(**summary_runtime.client_kwargs)
    with model_call_scope(session_call(getattr(session, "project_id", None), session_id=session_id,
                                       user_id=getattr(session, "user_id", None))):
        response = await provider.chat(
            messages=[
                {"role": "system", "content": render_prompt("context.summarizer.system")},
                {"role": "user", "content": user_prompt},
            ],
            model=summary_runtime.model,
            temperature=0,
            max_tokens=600,
        )
    structured_summary = parse_summary_response(
        response.get("content") or "",
        fallback_goal=_first_user_goal(all_messages),
        existing_summary_json=existing_summary_json,
        new_messages=new_messages,
    )
    structured_summary, validated_references = apply_reference_markers(structured_summary, evidence_refs)
    metadata["summary_json"] = structured_summary
    metadata["summary"] = render_structured_summary(structured_summary)
    metadata["summary_message_count"] = len(messages_to_summarise)
    metadata["summary_references"] = validated_references
    metadata["summary_evidence_map"] = evidence_refs
    metadata["summary_source_last_message_id"] = source_last_message_id
    session.metadata_ = metadata
    await db.commit()


def build_history_messages(
    all_history: list,
    session_summary: str | dict | None,
    *,
    include_summary: bool = True,
    recent_window: int | None = None,
    summary_references: list | None = None,
) -> tuple[list[dict], list]:
    """Return (injected_context_messages, recent_messages).

    injected_context_messages: 0–2 messages injecting the summary before recent history.
    recent_messages: the WINDOW_SIZE most recent messages to send verbatim.
    summary_references: optional validated reference ids attached to the summary;
    when present, a short drill-back hint is appended to the injected summary.
    """
    window_size = recent_window if recent_window is not None and recent_window > 0 else WINDOW_SIZE
    if include_summary and len(all_history) > SUMMARIZE_THRESHOLD and session_summary:
        recent = all_history[-window_size:]
        if isinstance(session_summary, dict):
            rendered_summary = json.dumps(session_summary, ensure_ascii=True, sort_keys=True)
            tag_name = "session_summary_json"
        else:
            rendered_summary = str(session_summary)
            tag_name = "session_summary"
        summary_content = render_prompt(
            "context.summary.injected", tag_name=tag_name, rendered_summary=rendered_summary
        )
        if summary_references:
            summary_content += "\n" + render_prompt("context.summary.drill_back_hint")
        context_msgs = [
            {"role": "user", "content": summary_content},
            {"role": "assistant", "content": render_prompt("context.summary.assistant_ack")},
        ]
    else:
        recent = all_history[-window_size:] if window_size and len(all_history) > window_size else all_history
        context_msgs = []

    return context_msgs, recent
