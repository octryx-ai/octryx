from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Approval,
    Message,
    MessageFeedback,
    Session,
    TeamMember,
    ToolCall,
    UsageEvent,
)
from ...services.session.run_state import get_session_run_status
from ...time_utils import ensure_utc

KNOWLEDGE_QUERY_TOOLS = {"knowledge_search", "knowledge_read", "knowledge_changes"}
#: The governed Memory lobe is read and written through these tools.
MEMORY_READ_TOOLS = {"memory_recall"}
MEMORY_WRITE_TOOLS = {"memory_remember"}


def date_matches(value: Any, target: date) -> bool:
    dt = ensure_utc(value)
    return bool(dt and dt.date() == target)


def _json_has_hits(result: Any) -> bool:
    if result in (None, "", [], {}, ()):
        return False
    if isinstance(result, dict):
        for key in ("evidence", "items", "results", "entries", "matches", "tickets", "pages"):
            value = result.get(key)
            if isinstance(value, list) and value:
                return True
        return bool(result)
    if isinstance(result, list):
        return len(result) > 0
    return True


def _session_duration_minutes(session: Session, latest_message_at: Any) -> float | None:
    started = ensure_utc(session.started_at)
    ended = ensure_utc(session.ended_at) or ensure_utc(latest_message_at)
    if started is None or ended is None or ended < started:
        return None
    return max(0.0, (ended - started).total_seconds() / 60.0)


@dataclass
class MetricBundle:
    sessions: list[Session]
    tool_calls: list[ToolCall]
    approvals: list[Approval]
    usage_events: list[UsageEvent]
    feedback: list[MessageFeedback]
    latest_message_at: dict[str, Any]
    message_session_ids: dict[str, str]


def summarize_metrics(bundle: MetricBundle, *, session_ids: set[str]) -> dict[str, Any]:
    relevant_sessions = [session for session in bundle.sessions if session.id in session_ids]
    relevant_tool_calls = [row for row in bundle.tool_calls if row.session_id in session_ids]
    relevant_approvals = [row for row in bundle.approvals if row.session_id in session_ids]
    relevant_usage = [row for row in bundle.usage_events if row.session_id in session_ids]
    relevant_feedback = [
        row for row in bundle.feedback if bundle.message_session_ids.get(row.message_id) in session_ids
    ]

    durations = [
        duration
        for duration in (
            _session_duration_minutes(session, bundle.latest_message_at.get(session.id))
            for session in relevant_sessions
        )
        if duration is not None
    ]
    provider_costs: dict[str, float] = defaultdict(float)
    for row in relevant_usage:
        provider_costs[str(row.provider or "unknown")] += float(row.cost or 0.0)

    return {
        "sessions_total": len(relevant_sessions),
        "sessions_completed": sum(1 for session in relevant_sessions if get_session_run_status(session) == "completed"),
        "sessions_failed": sum(1 for session in relevant_sessions if get_session_run_status(session) == "failed"),
        "avg_session_duration_minutes": round(sum(durations) / len(durations), 4) if durations else None,
        "tool_calls_total": len(relevant_tool_calls),
        "tool_calls_success": sum(1 for row in relevant_tool_calls if str(row.status or "success") == "success"),
        "tool_calls_failed": sum(1 for row in relevant_tool_calls if str(row.status or "success") != "success"),
        "approvals_requested": len(relevant_approvals),
        "approvals_approved": sum(1 for row in relevant_approvals if str(row.status or "") == "approved"),
        "total_cost": round(sum(float(row.cost or 0.0) for row in relevant_usage), 4),
        "cost_by_provider": {key: round(value, 4) for key, value in sorted(provider_costs.items())},
        "total_tokens_in": sum(int(row.tokens_in or 0) for row in relevant_usage),
        "total_tokens_out": sum(int(row.tokens_out or 0) for row in relevant_usage),
        "knowledge_queries": sum(
            1
            for row in relevant_tool_calls
            if row.tool_name in KNOWLEDGE_QUERY_TOOLS or "knowledge" in str(row.tool_name or "")
        ),
        "knowledge_hits": sum(
            1
            for row in relevant_tool_calls
            if (row.tool_name in KNOWLEDGE_QUERY_TOOLS or "knowledge" in str(row.tool_name or ""))
            and _json_has_hits(row.result)
        ),
        "memory_reads": sum(1 for row in relevant_tool_calls if row.tool_name in MEMORY_READ_TOOLS),
        "memory_writes": sum(1 for row in relevant_tool_calls if row.tool_name in MEMORY_WRITE_TOOLS),
        "positive_feedback": sum(1 for row in relevant_feedback if int(row.rating or 0) > 0),
        "negative_feedback": sum(1 for row in relevant_feedback if int(row.rating or 0) < 0),
    }


async def load_metric_bundle_for_date(
    db: AsyncSession,
    *,
    target_date: date,
    session_ids: set[str],
    sessions: list[Session],
) -> MetricBundle:
    messages = (await db.execute(select(Message).where(Message.session_id.in_(session_ids)))).scalars().all()
    latest_message_at: dict[str, Any] = {}
    for message in messages:
        current = latest_message_at.get(message.session_id)
        if current is None or (message.created_at and current and message.created_at > current):
            latest_message_at[message.session_id] = message.created_at

    tool_calls = (await db.execute(select(ToolCall).where(ToolCall.session_id.in_(session_ids)))).scalars().all()
    approvals = (await db.execute(select(Approval).where(Approval.session_id.in_(session_ids)))).scalars().all()
    usage_events = (await db.execute(select(UsageEvent).where(UsageEvent.session_id.in_(session_ids)))).scalars().all()
    feedback = (
        (
            await db.execute(
                select(MessageFeedback)
                .join(Message, Message.id == MessageFeedback.message_id)
                .where(Message.session_id.in_(session_ids))
            )
        )
        .scalars()
        .all()
    )
    message_session_ids = {message.id: message.session_id for message in messages}

    return MetricBundle(
        sessions=sessions,
        tool_calls=[row for row in tool_calls if date_matches(row.created_at, target_date)],
        approvals=[row for row in approvals if date_matches(row.created_at, target_date)],
        usage_events=[row for row in usage_events if date_matches(row.created_at, target_date)],
        feedback=[row for row in feedback if date_matches(row.created_at, target_date)],
        latest_message_at=latest_message_at,
        message_session_ids=message_session_ids,
    )


def group_session_ids_by_project(sessions: list[Session]) -> dict[str, set[str]]:
    session_ids_by_project: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        session_ids_by_project[str(session.project_id)].add(session.id)
    return session_ids_by_project


def build_team_users(team_members: list[TeamMember]) -> dict[str, set[str]]:
    team_users: dict[str, set[str]] = defaultdict(set)
    for row in team_members:
        team_users[row.team_id].add(row.user_id)
    return team_users


def team_session_ids_for_project(sessions: list[Session], *, project_id: str, team_user_ids: set[str]) -> set[str]:
    return {session.id for session in sessions if session.project_id == project_id and session.user_id in team_user_ids}
