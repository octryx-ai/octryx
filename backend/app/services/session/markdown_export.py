"""Markdown evidence export for chat sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, User
from ...models import Session as AgentSession
from ...time_utils import utc_isoformat
from .export_bundle import load_session_export_bundle, session_export_title


@dataclass(frozen=True, slots=True)
class SessionMarkdownExport:
    content: str
    filename: str


async def build_session_markdown_export(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    exported_by: User | None = None,
) -> SessionMarkdownExport:
    bundle = await load_session_export_bundle(
        db,
        session_id=session_id,
        user_id=user_id,
        exported_by=exported_by,
    )
    title = session_export_title(bundle.session, fallback="Thread Export")
    return SessionMarkdownExport(
        content=render_session_markdown_export(
            session=bundle.session,
            messages=bundle.messages,
            tool_calls=bundle.tool_calls,
        ),
        filename=_markdown_export_filename(title=title, session_id=bundle.session.id),
    )


def render_session_markdown_export(
    *,
    session: AgentSession,
    messages: list[Message],
    tool_calls: list[ToolCall],
) -> str:
    title = session_export_title(session, fallback="Thread Export")
    lines = [
        f"# {title}",
        "",
        f"- Session: `{session.id}`",
        f"- Started: `{utc_isoformat(session.started_at) or '—'}`",
        "",
        "## Transcript",
        "",
    ]
    tool_calls_by_message_id: dict[str, list[ToolCall]] = {}
    for tool_call in tool_calls:
        if tool_call.message_id:
            tool_calls_by_message_id.setdefault(tool_call.message_id, []).append(tool_call)
    for message in messages:
        role = str(message.role or "").strip().lower() or "message"
        lines.append(f"### {role.title()}")
        lines.append("")
        lines.append(message.content or "")
        lines.append("")
        related_calls = tool_calls_by_message_id.get(message.id) or []
        if related_calls:
            lines.append("#### Tools")
            lines.append("")
            for tool_call in related_calls:
                lines.append(f"- `{tool_call.tool_name}` · `{tool_call.status}`")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _markdown_export_filename(*, title: str, session_id: str) -> str:
    safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", title.strip()).strip("-.")
    return f"{(safe_title or session_id)[:80]}.md"


__all__ = ["SessionMarkdownExport", "build_session_markdown_export", "render_session_markdown_export"]
