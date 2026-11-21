"""Record an executed tool call: repository state, the ``ToolCall`` row, the end event and the turn snapshot."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ....models import ToolCall
from ....services.artifact_store import (
    build_tool_result_storage_pointer,
    persist_tool_artifact_payload,
    should_externalize_payload,
)
from ....services.request_context import get_current_request_id
from ....services.secure_work.coding.coding_workspaces import record_bitbucket_prepare_result
from ....services.session.entity import list_session_entities, upsert_session_entities_from_tool_result
from ....services.session.runtime_events import publish_tool_call_end
from ....services.tool_result_compression import compress_tool_result_for_model
from ....services.tool_result_compression.budget import (
    compact_result_token_budget,
    enforce_compact_result_budget,
    strip_compact_result_budget_hint,
)
from ....tools.results import tool_call_status
from ....tools.tool_names import ToolName
from .turn_diff import TurnDiffTracker

WORKING_SET_COMPACT_RESULT_TOKEN_BUDGET = 2200


async def apply_repository_tool_effects(
    db: AsyncSession,
    *,
    tool_context: ToolContext,
    tool_name: str,
    tool_args: dict[str, Any],
    result: dict[str, Any],
    latest_repo_state: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Track the prepared repository and branch, and attach the delivery record of a created pull request."""
    if tool_name == ToolName.PREPARE_BITBUCKET_REPOSITORY and "error" not in result:
        local_path = str(result.get("local_path") or "").strip()
        if local_path:
            await record_bitbucket_prepare_result(
                db,
                session_id=tool_context.session_id,
                current_user_id=tool_context.user_id,
                result=result,
            )
            latest_repo_state = {
                "local_path": local_path,
                "repo_readme_path": str(Path(local_path) / "README.md"),
                "branch_name": str(result.get("branch_name") or "").strip(),
                "relative_path": str(result.get("relative_path") or "").strip(),
            }
    elif tool_name == ToolName.COMMIT_AND_PUSH_REPOSITORY_BRANCH and "error" not in result and latest_repo_state:
        latest_repo_state["branch_name"] = str(
            result.get("branch_name") or latest_repo_state.get("branch_name") or ""
        ).strip()
    elif tool_name == "create_bitbucket_pull_request" and "error" not in result:
        from ....services.secure_work.coding.coding_pr_delivery import record_bitbucket_pull_request_delivery

        delivery = await record_bitbucket_pull_request_delivery(
            tool_context.db,
            session_id=tool_context.session_id,
            user_id=tool_context.user_id,
            tool_params=tool_args,
            tool_result=result,
            project_config=tool_context.project_config,
        )
        if delivery is not None:
            result = {**result, "work_delivery": delivery}
    return result, latest_repo_state


@dataclass(kw_only=True)
class ToolCallRecord:
    """The inputs of ``record_tool_call``; the caller builds it once the result is final."""

    db: AsyncSession
    tool_context: ToolContext
    assistant_message_id: str
    tool_call_id: str
    request_id: str | None
    tool_name: str
    persistable_tool_args: dict[str, Any]
    result: dict[str, Any]
    cache_meta: dict[str, Any] | None
    cache_hit_kind: str | None
    duration_ms: int
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]]
    turn_diff_tracker: TurnDiffTracker
    context_snapshot: dict[str, Any]


async def _compact_result_for_model(record: ToolCallRecord) -> dict[str, Any]:
    compact_result = await compress_tool_result_for_model(
        record.db,
        session_id=record.tool_context.session_id,
        tool_name=record.tool_name,
        result=record.result,
        request_id=record.tool_context.request_id or get_current_request_id(),
        fallback=record.compact_tool_result_for_model,
    )
    compact_result = enforce_compact_result_budget(
        compact_result,
        token_budget=compact_result_token_budget(compact_result, default=WORKING_SET_COMPACT_RESULT_TOKEN_BUDGET),
    )
    compact_result = strip_compact_result_budget_hint(compact_result)
    if not isinstance(compact_result, dict):
        compact_result = {"value": compact_result}
    return compact_result


async def _stored_result(record: ToolCallRecord, artifact_id: str, compact_result: dict[str, Any]) -> dict[str, Any]:
    """The result kept on the ``ToolCall`` row: the payload itself, or a pointer when it is externalized."""
    result = record.result
    if not should_externalize_payload(result):
        return result
    artifact_metadata = await persist_tool_artifact_payload(
        record.db,
        artifact_id=artifact_id,
        session_id=record.tool_context.session_id,
        message_id=record.assistant_message_id,
        tool_name=record.tool_name,
        payload=result,
        preview={"compact_result": compact_result},
    )
    stored_result = build_tool_result_storage_pointer(
        artifact_id=artifact_id,
        payload_size_bytes=int(artifact_metadata.get("payload_size_bytes") or 0),
        content_sha256=str(artifact_metadata.get("content_sha256") or ""),
        preview={"compact_result": compact_result},
    )
    if isinstance(result.get("execution_event"), dict):
        stored_result["execution_event"] = dict(result["execution_event"])
    if isinstance(result.get("execution_events"), list):
        stored_result["execution_events"] = list(result["execution_events"])
    return stored_result


async def _publish_end(record: ToolCallRecord, artifact_id: str, compact_result: dict[str, Any]) -> None:
    await publish_tool_call_end(
        session_id=record.tool_context.session_id,
        turn_id=record.request_id,
        tool_call_id=record.tool_call_id,
        persisted_tool_call_id=artifact_id,
        tool_name=record.tool_name,
        status=tool_call_status(record.result),
        duration_ms=record.duration_ms,
        artifact_id=artifact_id,
        result_preview=compact_result,
        cache=record.cache_meta,
        request_id=record.request_id,
    )


async def record_tool_call(record: ToolCallRecord) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Persist and publish the call; returns the turn's tool result, the artifact id and the compact result."""
    db, tool_context = record.db, record.tool_context
    updated_entities: list[dict[str, Any]] = []
    if record.cache_hit_kind != "session":
        updated_entities = await upsert_session_entities_from_tool_result(
            db,
            session_id=tool_context.session_id,
            message_id=record.assistant_message_id,
            tool_name=record.tool_name,
            result=record.result,
        )
    compact_result = await _compact_result_for_model(record)
    artifact_id = str(uuid.uuid4())
    stored_result = await _stored_result(record, artifact_id, compact_result)
    db.add(
        ToolCall(
            id=artifact_id,
            session_id=tool_context.session_id,
            message_id=record.assistant_message_id,
            tool_name=record.tool_name,
            parameters=record.persistable_tool_args,
            result=stored_result,
            status=tool_call_status(record.result),
            duration_ms=record.duration_ms,
            request_id=record.request_id,
        )
    )
    tool_result = {
        "artifact_id": artifact_id,
        "tool_name": record.tool_name,
        "tool_call_id": record.tool_call_id,
        "result": record.result,
        "compact_result": compact_result,
    }
    if record.cache_meta:
        tool_result["cache"] = record.cache_meta
    await _publish_end(record, artifact_id, compact_result)
    record.turn_diff_tracker.record_tool_call(record.tool_name, record.persistable_tool_args, record.result)
    if updated_entities:
        record.context_snapshot["session_entities"] = await list_session_entities(
            db,
            session_id=tool_context.session_id,
            limit=12,
        )
    record.context_snapshot["turn_diff"] = record.turn_diff_tracker.to_dict()
    return tool_result, artifact_id, compact_result
