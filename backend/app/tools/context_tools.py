"""Session-level context freeze / release tools."""

from __future__ import annotations

from sqlalchemy import select

from ..models import Message
from ..services.context_checkpoint import (
    create_context_checkpoint,
    get_active_context_checkpoint,
    release_context_checkpoint,
)
from ..services.tool_artifact import load_tool_artifact_payload
from .context import ToolContext

_EVIDENCE_EXCERPT_CHARS = 500


class FreezeContextTool:
    name = "freeze_context"
    description = (
        "Freeze the current session context under a named checkpoint. "
        "After freezing, no further tool calls are allowed until `release_context` is called."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        if not context.db or not context.session_id:
            return {"error": "No active database session"}
        checkpoint_name = str(params.get("checkpoint_name") or "").strip()
        if not checkpoint_name:
            return {"error": "checkpoint_name is required"}
        snapshot = context.turn_context_snapshot if isinstance(context.turn_context_snapshot, dict) else {}
        try:
            checkpoint = await create_context_checkpoint(
                context.db,
                session_id=context.session_id,
                checkpoint_name=checkpoint_name,
                context_snapshot=snapshot,
            )
        except ValueError as exc:
            active = await get_active_context_checkpoint(context.db, session_id=context.session_id)
            return {
                "error": str(exc),
                "active_checkpoint_name": active.checkpoint_name if active else "",
            }
        return {
            "status": checkpoint.status,
            "checkpoint_id": checkpoint.id,
            "checkpoint_name": checkpoint.checkpoint_name,
            "snapshot_keys": sorted(snapshot.keys()),
            "tool_calls_blocked_until_release": True,
        }


class ReleaseContextTool:
    name = "release_context"
    description = (
        "Release or roll back the active frozen session checkpoint. "
        "Use `action=release` to continue normally or `action=rollback` to abandon the frozen branch."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        if not context.db or not context.session_id:
            return {"error": "No active database session"}
        checkpoint_name = str(params.get("checkpoint_name") or "").strip() or None
        action = str(params.get("action") or "release").strip().lower()
        try:
            checkpoint = await release_context_checkpoint(
                context.db,
                session_id=context.session_id,
                checkpoint_name=checkpoint_name,
                action=action,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {
            "status": checkpoint.status,
            "checkpoint_id": checkpoint.id,
            "checkpoint_name": checkpoint.checkpoint_name,
            "tool_calls_allowed": True,
        }


class LoadToolArtifactTool:
    name = "load_tool_artifact"
    description = (
        "Load more detail for a prior tool result by artifact_id. "
        "Use this only when an older tool snapshot in context is too compact. "
        "Optional `path` can target a nested field like `items.0`."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        if not context.db or not context.session_id:
            return {"error": "No active database session"}
        artifact_id = str(params.get("artifact_id") or "").strip()
        detail_level = str(params.get("detail_level") or "excerpt").strip().lower() or "excerpt"
        path = str(params.get("path") or "").strip() or None
        max_chars = int(params.get("max_chars") or 4000)
        max_items = int(params.get("max_items") or 20)
        return await load_tool_artifact_payload(
            context.db,
            session_id=context.session_id,
            artifact_id=artifact_id,
            detail_level=detail_level,
            max_chars=max_chars,
            max_items=max_items,
            path=path,
        )


class GetSessionSummaryEvidenceTool:
    name = "get_session_summary_evidence"
    description = (
        "Load the full stored session message behind a session summary evidence reference. "
        "Pass `reference_id` like `msg:<message_id>` or `tool_call:<tool_call_id>` from the "
        "summary. Read-only and limited to the current session."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, object]:
        if not context.db or not context.session_id:
            return {"error": "No active database session"}
        reference_id = str(params.get("reference_id") or "").strip()
        detail_level = str(params.get("detail_level") or "excerpt").strip().lower()
        if detail_level not in {"excerpt", "full"}:
            detail_level = "excerpt"
        kind, _, ref_value = reference_id.partition(":")
        kind = kind.strip().lower()
        ref_value = ref_value.strip()
        if kind not in {"msg", "tool_call"} or not ref_value:
            return {
                "found": False,
                "reference_id": reference_id,
                "error": "reference_id must look like 'msg:<message_id>' or 'tool_call:<tool_call_id>'",
            }
        matched_tool_item: dict | None = None
        if kind == "msg":
            result = await context.db.execute(
                select(Message).where(Message.id == ref_value, Message.session_id == context.session_id)
            )
            message = result.scalar_one_or_none()
        else:
            message, matched_tool_item = await self._find_tool_call_message(context, ref_value)
        if message is None:
            return {
                "found": False,
                "reference_id": reference_id,
                "error": "Reference not found in this session",
            }
        content = str(message.content or "")
        if detail_level == "excerpt" and len(content) > _EVIDENCE_EXCERPT_CHARS:
            content = content[:_EVIDENCE_EXCERPT_CHARS].rstrip() + "..."
        payload: dict[str, object] = {
            "found": True,
            "reference_id": reference_id,
            "message_id": str(message.id or ""),
            "role": str(message.role or ""),
            "created_at": message.created_at.isoformat() if message.created_at else "",
            "detail_level": detail_level,
            "content": content,
        }
        tool_names = _extract_tool_names(message.tool_calls)
        if tool_names:
            payload["tool_names"] = tool_names
        if matched_tool_item is not None:
            function = matched_tool_item.get("function") if isinstance(matched_tool_item.get("function"), dict) else {}
            payload["tool_name"] = str(
                function.get("name") or matched_tool_item.get("tool_name") or matched_tool_item.get("name") or ""
            )
            if detail_level == "full":
                payload["tool_item"] = matched_tool_item
        return payload

    @staticmethod
    async def _find_tool_call_message(context: ToolContext, tool_call_id: str) -> tuple[Message | None, dict | None]:
        result = await context.db.execute(
            select(Message).where(Message.session_id == context.session_id).order_by(Message.created_at.asc())
        )
        for message in result.scalars().all():
            for item in message.tool_calls if isinstance(message.tool_calls, list) else []:
                if isinstance(item, dict) and str(item.get("id") or "") == tool_call_id:
                    return message, item
            for item in message.tool_results if isinstance(message.tool_results, list) else []:
                if isinstance(item, dict) and str(item.get("tool_call_id") or item.get("id") or "") == tool_call_id:
                    return message, item
        return None, None


def _extract_tool_names(tool_calls: object) -> list[str]:
    if not isinstance(tool_calls, list):
        return []
    names: list[str] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names
