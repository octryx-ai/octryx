"""``propose_write_plan``: the chat proposes every write of a request once; the person confirms once."""

from __future__ import annotations

from typing import Any

from ..services.run_capability.chat_write_plan import (
    PLAN_KIND,
    PROPOSE_WRITE_PLAN,
    active_plan,
    current_request,
    is_chat_plan_write,
    new_plan_id,
    plan_covers_all,
    trusted_for_chat,
    trusted_skips_plan,
    uncovered,
)
from ..services.run_capability.chat_writes import chat_connector_write_permitted, chat_connector_writes_enabled
from ..services.secret_masking import masked
from .context import ToolContext
from .jira_impl._jira_issue_type_args import normalize_issue_type_args


def _requested_writes(params: dict[str, Any]) -> list[dict[str, Any]]:
    writes = params.get("writes")
    if isinstance(writes, dict):
        writes = [writes]  # a weak model sends one write as an object
    result = []
    for item in writes if isinstance(writes, list) else []:
        if isinstance(item, dict):
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            result.append({"tool": str(item.get("tool") or "").strip(), "fields": dict(fields),
                           "why": str(item.get("why") or "").strip() or None})
    return result


# A write's fields in the one spelling its tool executes, so the card shows exactly what will be sent (otherwise
# ``issuetype: "Epic"`` was shown and would have run as the default Task).
_FIELD_NORMALIZERS = {"create_jira_ticket": normalize_issue_type_args}


def _normalized(writes: list[dict[str, Any]]) -> list[dict[str, str]]:
    invalid = []
    for write in writes:
        normalize = _FIELD_NORMALIZERS.get(write["tool"])
        if normalize is None:
            continue
        fields, problem = normalize(write["fields"])
        if problem:
            invalid.append({"tool": write["tool"], "reason": problem})
        else:
            write["fields"] = fields
    return invalid


def _requested_scope(params: dict[str, Any]) -> list[dict[str, Any]]:
    scope = params.get("scope")
    return [{"kind": str(entry.get("kind") or "target"), "value": str(entry.get("value")).strip()}
            for entry in (scope if isinstance(scope, list) else [])
            if isinstance(entry, dict) and str(entry.get("value") or "").strip()]


def _invalid(writes: list[dict[str, Any]], context: ToolContext) -> list[dict[str, str]]:
    return [{"tool": write["tool"] or "(missing)", "reason": "not a write tool this chat may call"}
            for write in writes if not write["tool"] or not is_chat_plan_write(write["tool"], context)]


async def _write_preview(write: dict[str, Any], index: int, connection: str, context: ToolContext) -> dict[str, Any]:
    from ..services.tool_approval.previews import _chat_write_preview
    from .definitions import get_tool_definition_metadata

    shown = await _chat_write_preview(write["tool"], write["fields"], context, {"details": []})
    from ..services.secret_masking import sealed_fields

    # Shown and stored masked; the real fields stay sealed for the confirmed write (secret_masking).
    entry = {"index": index, "tool": write["tool"], "connector": get_tool_definition_metadata(write["tool"]).connector,
             "connection": connection or shown.get("connection") or None, **sealed_fields(write["fields"]),
             "why": write["why"],
             "details": list(shown.get("details") or [])}
    for key in ("title", "summary", "before", "after"):
        entry[key] = shown.get(key)
    return entry


def _flat_details(request: str, writes: list[dict[str, Any]], scope: list[dict[str, Any]]) -> list[str]:
    lines = [f"request: {request}"] if request else []
    for write in writes:
        via = f" via {write['connection']}" if write.get("connection") else ""
        # The write in words (``approval/presentation``); the tool's name stays in the entry's ``tool``.
        lines.append(f"write {write['index'] + 1}: {write.get('title') or write['tool']}{via}")
        lines.extend(f"  {line}" for line in write["details"] if not line.startswith(("tool: ", "connection: ")))
    lines.extend(f"scope: {entry['kind']} {entry['value']}" for entry in scope)
    return lines


def _plan_scope(requested: list[dict[str, Any]], writes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from ..services.run_capability.chat_write_plan import call_targets

    scope = [{**entry, "named_by": "scope"} for entry in requested]
    seen = {(entry["kind"], entry["value"].lower()) for entry in scope}
    for write in writes:
        for kind, value in call_targets(write["fields"]):
            if (kind, value) not in seen:
                seen.add((kind, value))
                scope.append({"kind": kind, "value": value, "named_by": "writes"})
    return scope


class ProposeWritePlanTool:
    name = PROPOSE_WRITE_PLAN
    description = "Propose every write of the request as one plan; the person confirms it once."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..models import Session

        if not chat_connector_writes_enabled(context):
            return {"error": "propose_write_plan is for a chat turn that writes; this run writes under its own "
                             "declared capability.", "code": "write_plan_not_chat"}
        writes = _requested_writes(params)
        if not writes:
            return {"error": "List at least one write: {tool, fields}.", "code": "write_plan_invalid", "invalid": []}
        invalid = _invalid(writes, context)
        if invalid:
            return {"error": "These are not write tools this chat may call; use the write tools you are offered.",
                    "code": "write_plan_invalid", "invalid": invalid}
        contradicting = _normalized(writes)
        if contradicting:
            return {"error": "Some writes contradict themselves; send each field once with the value the person "
                             "asked for.", "code": "write_plan_invalid", "invalid": contradicting}
        refusal = self._route_refusal(writes, context)
        if refusal is not None:
            return refusal
        session = await context.db.get(Session, context.session_id) if context.db is not None else None
        metadata = dict(session.metadata_ or {}) if session is not None else {}
        if session is None or not current_request(metadata) or not str(context.user_id or "").strip():
            return {"error": "No chat request is in flight to attach the plan to.", "code": "write_plan_no_turn"}
        workspace_id = session.project_id or next(iter(context.project_ids or []), None)
        if all(trusted_skips_plan(write["tool"]) for write in writes) and await trusted_for_chat(
                context.db, context.user_id, workspace_id):
            return {"status": "not_needed", "message": "Your role is trusted: perform the writes directly."}
        from ..services.tool_approval.previews import _connection_label

        connections = [_connection_label(write["tool"], write["fields"], context.project_config) for write in writes]
        plan = active_plan(metadata)
        if plan_covers_all(plan, writes, connections):
            # Name the calls to make, so the next model call is the write itself.
            return {"status": "confirmed", "plan_id": plan.get("plan_id"),
                    "message": "Already confirmed. Call these write tools now, without proposing the plan again.",
                    "next_calls": [{"tool": write["tool"], "arguments": masked(write["fields"])} for write in writes]}
        pending = [(write, connection) for write, connection in zip(writes, connections, strict=True)
                   if uncovered(plan, write["tool"], write["fields"], connection)]
        return await self._ask(params, pending, plan, metadata, context)

    @staticmethod
    def _route_refusal(writes: list[dict[str, Any]], context: ToolContext) -> dict[str, Any] | None:
        from ..services.tool_approval.previews import chat_write_route_refusal

        for write in writes:
            if chat_connector_write_permitted(write["tool"], context):
                refusal = chat_write_route_refusal(write["tool"], write["fields"], context.project_config)
                if refusal is not None:
                    return {**refusal, "tool": write["tool"]}
        return None

    @staticmethod
    async def _ask(params: dict[str, Any], pending: list[tuple[dict[str, Any], str]], plan: dict[str, Any] | None,
                   metadata: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        from ..services.approval import ensure_approval_request
        from ..services.approval.presentation import plan_title
        from ..services.change_preview import build_change_request_fingerprint, upsert_change_preview

        request = str(params.get("request") or "").strip()
        writes = [await _write_preview(write, index, connection, context)
                  for index, (write, connection) in enumerate(pending)]
        scope = _plan_scope(_requested_scope(params), [write for write, _connection in pending])
        plan_id = new_plan_id()
        amendment = plan is not None
        payload = {
            "kind": PLAN_KIND, "plan_id": plan_id, "amends": plan.get("plan_id") if amendment else None,
            "request": request or (plan or {}).get("request") or "", "user_message_id": current_request(metadata),
            "title": plan_title(len(writes), amendment=amendment),
            "summary": "Confirm once: these writes then run without asking again.",
            "scope": scope, "writes": writes,
            "confirmed_writes": list(plan.get("writes") or []) if amendment else [],
            "details": _flat_details(request, writes, scope), "standing_rule": None,
            "toolName": PROPOSE_WRITE_PLAN, "approvalSubject": PROPOSE_WRITE_PLAN,
        }
        label = "Approve write plan amendment" if amendment else "Approve write plan"
        approval = await ensure_approval_request(context.db, requested_by=context.user_id,
                                                 session_id=context.session_id,
                                                 action=f"{label}: {request or plan_id}",
                                                 reason=payload["summary"])
        preview = await upsert_change_preview(
            context.db, tool_name=PROPOSE_WRITE_PLAN, preview_payload=payload,
            request_fingerprint=build_change_request_fingerprint(PROPOSE_WRITE_PLAN, params),
            session_id=context.session_id, approval_id=approval.id)
        return {"error": "Waiting for the person to confirm the write plan.", "status": "awaiting_confirmation",
                "plan_id": plan_id, "approval_required": True, "approval_id": approval.id,
                "approval_status": approval.status, "change_preview_id": preview.id,
                "blocked_by": "tool_approval_gate", "tool_name": PROPOSE_WRITE_PLAN}


__all__ = ["ProposeWritePlanTool"]
