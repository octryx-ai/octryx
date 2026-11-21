"""PDF evidence export for chat sessions."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, TurnTrace, User
from ...time_utils import utc_isoformat
from .export_bundle import (
    SessionExportBundle,
    exporter_label,
    load_session_export_bundle,
    session_export_filename,
    session_export_title,
)

MAX_JSON_EVIDENCE_CHARS = 12000
MAX_METADATA_CHARS = 4000
MAX_FILENAME_CHARS = 90


@dataclass(frozen=True, slots=True)
class SessionPdfExport:
    content: bytes
    filename: str


async def build_session_pdf_export(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str,
    exported_by: User | None = None,
) -> SessionPdfExport:
    bundle = await load_session_export_bundle(
        db,
        session_id=session_id,
        user_id=user_id,
        exported_by=exported_by,
    )
    title = session_export_title(bundle.session, fallback="Chat Evidence Export")
    lines = _unfenced_lines(_session_export_lines(
        title=title,
        bundle=bundle,
    ))
    filename = session_export_filename(title=title, session_id=bundle.session.id, suffix="pdf")
    return SessionPdfExport(content=render_text_pdf(lines, title=title), filename=filename)


def _unfenced_lines(lines: list[str]) -> list[str]:
    """The export's lines without fence markers: a PDF is read by people (fence only at a model's input).
    Stored tool results keep their fences for the model; the evidence a person exports shows the text."""
    from ..content_security.knowledge_fence import unfence_text

    return unfence_text("\n".join(lines)).split("\n")


def render_text_pdf(lines: list[str], *, title: str) -> bytes:
    """Render wrapped text lines into a simple WinAnsi PDF document."""

    page_width = 595
    page_height = 842
    margin_x = 42
    top_y = 800
    font_size = 9
    line_height = 12
    max_chars = 102
    lines_per_page = 62

    wrapped_lines: list[str] = []
    for line in lines:
        if not line:
            wrapped_lines.append("")
            continue
        wrapped = textwrap.wrap(
            line,
            width=max_chars,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(wrapped or [""])
    pages = [wrapped_lines[index : index + lines_per_page] for index in range(0, len(wrapped_lines), lines_per_page)]
    if not pages:
        pages = [[""]]

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # Filled after page object ids are known.
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    page_object_ids: list[int] = []
    for page_lines in pages:
        content = _pdf_page_content(
            page_lines,
            margin_x=margin_x,
            top_y=top_y,
            font_size=font_size,
            line_height=line_height,
        )
        content_object_id = len(objects) + 2
        page_object_id = len(objects) + 1
        page_object_ids.append(page_object_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")

    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects[1] = f"<< /Type /Pages /Count {len(page_object_ids)} /Kids [{kids}] >>".encode("ascii")

    return _build_pdf(objects, title=title)


def _session_export_lines(
    *,
    title: str,
    bundle: SessionExportBundle,
) -> list[str]:
    session = bundle.session
    exporter = exporter_label(bundle.exported_by)
    lines = [
        title,
        "=" * min(len(title), 90),
        "",
        "Export",
        f"- Exported at: {bundle.exported_at}",
        f"- Exported by: {exporter}",
        f"- Export access role: {bundle.access_role}",
        "",
        "Session",
        f"- Session id: {session.id}",
        f"- Owner user id: {session.user_id}",
        f"- Project id: {session.project_id or 'global'}",
        f"- Agent type: {session.agent_type or ''}",
        f"- Status: {session.status or ''}",
        f"- Run status: {session.run_status or ''}",
        f"- Started at: {utc_isoformat(session.started_at) or ''}",
        f"- Ended at: {utc_isoformat(session.ended_at) or ''}",
        f"- Parent session id: {session.parent_session_id or ''}",
        f"- Messages: {len(bundle.messages)}",
        f"- Tool calls: {len(bundle.tool_calls)}",
        f"- Turn traces: {len(bundle.turn_traces)}",
        "",
    ]
    metadata_text = _compact_json(session.metadata_ or {}, MAX_METADATA_CHARS)
    if metadata_text != "{}":
        lines.extend(["Session metadata", metadata_text, ""])

    tool_calls_by_message_id: dict[str, list[ToolCall]] = {}
    unmapped_tool_calls: list[ToolCall] = []
    for tool_call in bundle.tool_calls:
        if tool_call.message_id:
            tool_calls_by_message_id.setdefault(str(tool_call.message_id), []).append(tool_call)
        else:
            unmapped_tool_calls.append(tool_call)

    traces_by_message_id: dict[str, list[TurnTrace]] = {}
    unmapped_traces: list[TurnTrace] = []
    for trace in bundle.turn_traces:
        if trace.message_id:
            traces_by_message_id.setdefault(str(trace.message_id), []).append(trace)
        else:
            unmapped_traces.append(trace)

    lines.extend(["Transcript", ""])
    if not bundle.messages:
        lines.extend(["No messages recorded.", ""])
    for index, message in enumerate(bundle.messages, start=1):
        lines.extend(_message_lines(index, message))
        for tool_call in tool_calls_by_message_id.get(message.id, []):
            lines.extend(_tool_call_lines(tool_call, indent="  "))
        for trace in traces_by_message_id.get(message.id, []):
            lines.extend(_turn_trace_lines(trace, indent="  "))
        lines.append("")

    if unmapped_tool_calls:
        lines.extend(["Unmapped tool calls", ""])
        for tool_call in unmapped_tool_calls:
            lines.extend(_tool_call_lines(tool_call, indent=""))
        lines.append("")

    if unmapped_traces:
        lines.extend(["Unmapped turn traces", ""])
        for trace in unmapped_traces:
            lines.extend(_turn_trace_lines(trace, indent=""))
        lines.append("")

    lines.extend(
        [
            "Evidence notes",
            "- Message contents are exported in full.",
            "- Large JSON tool results and turn trace payloads are bounded and marked when truncated.",
        ]
    )
    return lines


def _message_lines(index: int, message: Message) -> list[str]:
    header_parts = [
        f"{index}. {str(message.role or 'message').upper()}",
        f"id={message.id}",
        f"created={utc_isoformat(message.created_at) or ''}",
    ]
    if message.model:
        header_parts.append(f"model={message.model}")
    if message.tokens_in:
        header_parts.append(f"tokens_in={message.tokens_in}")
    if message.tokens_out:
        header_parts.append(f"tokens_out={message.tokens_out}")
    if message.cost:
        header_parts.append(f"cost={float(message.cost):.6f}")
    lines = [" | ".join(header_parts)]
    content = str(message.content or "").splitlines() or ["<empty>"]
    lines.extend(f"  {line}" if line else "" for line in content)
    if message.tool_calls:
        lines.extend(
            [
                "  Message tool_calls:",
                _indent(_compact_json(message.tool_calls, MAX_JSON_EVIDENCE_CHARS), "    "),
            ]
        )
    if message.tool_results:
        lines.extend(
            [
                "  Message tool_results:",
                _indent(_compact_json(message.tool_results, MAX_JSON_EVIDENCE_CHARS), "    "),
            ]
        )
    return lines


def _tool_call_lines(tool_call: ToolCall, *, indent: str) -> list[str]:
    lines = [
        (
            f"{indent}Tool call: {tool_call.tool_name} | id={tool_call.id} | status={tool_call.status or ''} "
            f"| created={utc_isoformat(tool_call.created_at) or ''}"
        )
    ]
    if tool_call.duration_ms is not None:
        lines.append(f"{indent}- Duration ms: {tool_call.duration_ms}")
    if tool_call.request_id:
        lines.append(f"{indent}- Request id: {tool_call.request_id}")
    lines.extend(
        [
            f"{indent}- Parameters:",
            _indent(_compact_json(tool_call.parameters or {}, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
        ]
    )
    if tool_call.result is not None:
        lines.extend(
            [
                f"{indent}- Result:",
                _indent(_compact_json(tool_call.result, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
            ]
        )
    return lines


def _turn_trace_lines(trace: TurnTrace, *, indent: str) -> list[str]:
    lines = [
        (
            f"{indent}Turn trace: id={trace.id} | provider={trace.provider or ''} | model={trace.model or ''} "
            f"| created={utc_isoformat(trace.created_at) or ''}"
        )
    ]
    if trace.usage_json:
        lines.extend(
            [
                f"{indent}- Usage:",
                _indent(_compact_json(trace.usage_json, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
            ]
        )
    if trace.context_snapshot_json:
        lines.extend(
            [
                f"{indent}- Context snapshot:",
                _indent(_compact_json(trace.context_snapshot_json, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
            ]
        )
    if trace.tool_trace_json:
        lines.extend(
            [
                f"{indent}- Tool trace:",
                _indent(_compact_json(trace.tool_trace_json, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
            ]
        )
    if trace.raw_output:
        lines.extend(
            [
                f"{indent}- Raw output:",
                _indent(_compact_json(trace.raw_output, MAX_JSON_EVIDENCE_CHARS), indent + "  "),
            ]
        )
    return lines


def _compact_json(value: Any, max_chars: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=2)
    except TypeError:
        text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"\n... [truncated {len(text) - max_chars} characters]"


def _indent(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" if line else "" for line in str(text).splitlines())


def _pdf_page_content(
    lines: list[str],
    *,
    margin_x: int,
    top_y: int,
    font_size: int,
    line_height: int,
) -> bytes:
    commands = [b"BT", f"/F1 {font_size} Tf".encode("ascii"), f"1 0 0 1 {margin_x} {top_y} Tm".encode("ascii")]
    for index, line in enumerate(lines):
        if index:
            commands.append(f"0 -{line_height} Td".encode("ascii"))
        commands.append(_pdf_hex_text(line) + b" Tj")
    commands.append(b"ET")
    return b"\n".join(commands)


def _pdf_hex_text(text: str) -> bytes:
    normalized = str(text).replace("\t", "    ")
    normalized = "".join(char if char == "\n" or ord(char) >= 32 else " " for char in normalized)
    return b"<" + normalized.encode("cp1252", errors="replace").hex().upper().encode("ascii") + b">"


def _build_pdf(objects: list[bytes], *, title: str) -> bytes:
    output = bytearray(b"%PDF-1.4\n%\x93\x8c\x8b\x9e\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    info_object_id = len(objects) + 1
    offsets.append(len(output))
    output.extend(f"{info_object_id} 0 obj\n".encode("ascii"))
    output.extend(b"<< /Title " + _pdf_literal_string(title) + b" /Producer (Octryx) >>\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info {info_object_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _pdf_literal_string(value: str) -> bytes:
    encoded = str(value).encode("cp1252", errors="replace").decode("cp1252")
    escaped = encoded.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})".encode("cp1252", errors="replace")
