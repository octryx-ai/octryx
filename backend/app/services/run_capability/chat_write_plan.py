"""A chat's writes are confirmed once per request, as one plan."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable
from typing import Any

from ...time_utils import utc_now_aware
from ...tools.definitions.write_risk import OUTBOUND_MESSAGE_DEFINITION_NAMES
from .chat_writes import (
    chat_connector_write_permitted,
    chat_connector_writes_enabled,
    chat_platform_write_needs_confirmation,
)

PROPOSE_WRITE_PLAN = "propose_write_plan"
PLAN_KIND = "write_plan"
PLAN_METADATA_KEY = "chat_write_plan"
PLAN_POLICY = "chat_write_plan"
CODE_PLAN_REQUIRED = "write_plan_required"
CODE_AMENDMENT_REQUIRED = "write_plan_amendment_required"
_CURRENT_TURN_KEY = "current_turn_user_message_id"  # = session.turn_approval_state.CURRENT_TURN_USER_MESSAGE_KEY

# Arguments that name *where* a write lands. Free text (summary, description, body) is never a target. ``base_branch``
# and ``start_point`` are where a new branch starts from (a read), so they are not here.
TARGET_PARAMS: dict[str, str] = {
    "project_key": "jira_project", "project": "jira_project",
    "ticket_id": "jira_issue", "ticket_ids": "jira_issue", "issue_key": "jira_issue", "parent_key": "jira_issue",
    "epic_key": "jira_issue", "issue_id": "jira_issue", "issue_number": "jira_issue",
    "space_key": "confluence_space", "page_id": "confluence_page", "parent_page_id": "confluence_page",
    "repo_slug": "repository", "repository": "repository", "repo": "repository",
    "branch_name": "branch", "branch": "branch", "from_branch": "branch", "to_branch": "branch",
    "source_branch": "branch", "target_branch": "branch", "destination_branch": "branch", "ref": "branch",
    "pr_id": "pull_request", "pr_number": "pull_request", "mr_iid": "pull_request",
    "work_item": "work_item", "work_item_id": "work_item",
    "reporter_email": "recipient", "attendees": "recipient", "to_user_id": "recipient", "responder_ids": "recipient",
    "run_id": "run",
    "namespace": "target", "release_name": "target", "app_name": "target", "application": "target",
    "instance_ids": "target", "vm_name": "target", "function_name": "target", "pipeline_name": "target",
    "version_id": "target", "incident_id": "target", "sprint_id": "target", "board_id": "target",
}
# Keys of a write's result that name what it created (an issue key, a page or work-item id, a branch).
_CREATED_RESULT_KEYS = ("key", "id", "source_key", "issue_key", "ticket_id", "page_id", "work_item_id", "pr_id",
                        "pr_number", "mr_iid", "number", "branch_name", "branch", "issue_number")
_ITEM_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)-\d+$")


def _norm(value: Any) -> str:
    return str(value).strip().lower() if value not in (None, "") else ""


def _values(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for item in items if not isinstance(item, (dict, list)) and (text := _norm(item))]


def call_targets(params: dict[str, Any] | None) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for key, value in (params or {}).items():
        kind = TARGET_PARAMS.get(str(key))
        if kind:
            targets.extend((kind, item) for item in _values(value))
    return list(dict.fromkeys(targets))


def is_chat_plan_write(tool_name: str, context: Any) -> bool:
    name = str(tool_name or "").strip()
    return (chat_connector_write_permitted(name, context) or chat_platform_write_needs_confirmation(name, context)
            or (name in OUTBOUND_MESSAGE_DEFINITION_NAMES and chat_connector_writes_enabled(context)))


def trusted_skips_plan(tool_name: str) -> bool:
    return str(tool_name or "").strip() not in OUTBOUND_MESSAGE_DEFINITION_NAMES


# ── The plan record ─────────────────────────────────────────────────────────


def current_request(metadata: dict[str, Any] | None) -> str:
    return str((metadata or {}).get(_CURRENT_TURN_KEY) or "").strip()


def active_plan(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    plan = (metadata or {}).get(PLAN_METADATA_KEY)
    request = current_request(metadata)
    if not isinstance(plan, dict) or not request or plan.get("user_message_id") != request:
        return None
    return plan


def _scope_values(plan: dict[str, Any]) -> set[str]:
    named = {_norm(entry.get("value")) for entry in plan.get("scope") or [] if isinstance(entry, dict)}
    for write in plan.get("writes") or []:
        named.update(value for _kind, value in call_targets(write.get("fields")))
    named.update(_norm(value) for value in plan.get("created") or [])
    return {value for value in named if value}


def _in_scope(value: str, scope: set[str]) -> bool:
    if value in scope:
        return True
    match = _ITEM_KEY.match(value)
    return bool(match) and match.group(1).lower() in scope  # an item key is covered by its project


def uncovered(plan: dict[str, Any] | None, tool_name: str, params: dict[str, Any] | None,
              connection: str = "") -> list[str]:
    if plan is None:
        return ["no confirmed plan"]
    name = str(tool_name or "").strip()
    listed = [write for write in plan.get("writes") or [] if write.get("tool") == name]
    if not listed:
        return [f"tool {name}"]
    reasons: list[str] = []
    connections = {_norm(write.get("connection")) for write in listed} - {""}
    if connections and _norm(connection) and _norm(connection) not in connections:
        reasons.append(f"connection {connection}")
    scope = _scope_values(plan)
    reasons.extend(f"{kind} {value}" for kind, value in call_targets(params) if not _in_scope(value, scope))
    return reasons


def plan_entry(write: dict[str, Any]) -> dict[str, Any]:
    from ..secret_masking import SEALED_KEY

    entry = {"tool": write.get("tool"), "connection": write.get("connection") or None,
             "fields": dict(write.get("fields") or {})}
    if write.get(SEALED_KEY):
        entry[SEALED_KEY] = write[SEALED_KEY]  # the real fields, encrypted (secret_masking)
    return entry


def merged_plan(current: dict[str, Any] | None, proposal: dict[str, Any], *, confirmed_by: str) -> dict[str, Any]:
    same_request = current is not None and current.get("user_message_id") == proposal.get("user_message_id")
    base = dict(current) if same_request else {"plan_id": proposal.get("plan_id"), "writes": [], "scope": [],
                                                 "created": []}
    base["user_message_id"] = proposal.get("user_message_id")
    base["request"] = base.get("request") or proposal.get("request")
    base["writes"] = [*base.get("writes", []), *(plan_entry(write) for write in proposal.get("writes") or [])]
    base["scope"] = [*base.get("scope", []), *({"kind": entry.get("kind"), "value": entry.get("value")}
                                               for entry in proposal.get("scope") or [])]
    base["confirmed_by"] = confirmed_by
    base["confirmed_at"] = utc_now_aware().isoformat()
    base.setdefault("approvals", []).append(proposal.get("approval_id"))
    return base


def new_plan_id() -> str:
    return f"wp_{uuid.uuid4().hex[:12]}"


def plan_view(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    plan = active_plan(metadata)
    if plan is None:
        return None
    return {"planId": plan.get("plan_id"), "request": plan.get("request"), "confirmedAt": plan.get("confirmed_at"),
            "confirmedBy": plan.get("confirmed_by"), "writes": list(plan.get("writes") or []),
            "scope": list(plan.get("scope") or []), "created": list(plan.get("created") or [])}


# ── Server side: session, trusted role, approval ─────────────────────────────


async def _session(db: Any, session_id: str | None) -> Any:
    from ...models import Session

    if db is None or not session_id:
        return None
    return await db.get(Session, session_id)


async def trusted_for_chat(db: Any, user_id: str | None, workspace_id: str | None) -> bool:
    try:
        from ..work_role_model.effective import effective_permission  # type: ignore[import-not-found]
    except ImportError:
        return False
    if db is None or not user_id or not workspace_id:
        return False
    try:
        return bool(getattr(await effective_permission(db, user_id, workspace_id), "trusted", False))
    except Exception:  # noqa: BLE001 - an unreadable role model never grants trust
        return False


def _connection(tool_name: str, params: dict[str, Any], project_config: Any) -> str:
    from ..tool_approval.previews import _connection_label

    return _connection_label(tool_name, params, project_config)


def _plan_refusal(tool_name: str, params: dict[str, Any], plan: dict[str, Any] | None,
                  reasons: list[str]) -> dict[str, Any]:
    plan_write = {"tool": tool_name, "fields": dict(params or {})}
    if plan is None:
        return {"error": ("Propose the plan first: call propose_write_plan once with every write this request needs "
                          "(tool and fields; this write is in plan_write). The person confirms the plan once, then "
                          "these writes run without asking again."),
                "code": CODE_PLAN_REQUIRED, "next_tool": PROPOSE_WRITE_PLAN, "plan_write": plan_write,
                "blocked_by": "tool_approval_gate", "tool_name": tool_name}
    return {"error": (f"This write is outside the confirmed plan ({', '.join(reasons)}). Amend the plan: call "
                      "propose_write_plan with just this write (plan_write); the person confirms the amendment once."),
            "code": CODE_AMENDMENT_REQUIRED, "next_tool": PROPOSE_WRITE_PLAN, "plan_write": plan_write,
            "outside_scope": reasons, "plan_id": plan.get("plan_id"), "blocked_by": "tool_approval_gate",
            "tool_name": tool_name}


async def plan_decision(tool_name: str, params: dict[str, Any], context: Any) -> dict[str, Any] | None:
    session = await _session(getattr(context, "db", None), getattr(context, "session_id", None))
    workspace_id = getattr(session, "project_id", None) or next(iter(getattr(context, "project_ids", None) or []),
                                                                None)
    if trusted_skips_plan(tool_name) and await trusted_for_chat(context.db, context.user_id, workspace_id):
        return None
    from ..ai_marking import with_markers, without_markers

    # The plan was confirmed without the agent marker line; it is matched without it and kept on the write.
    clean, lines = without_markers(params)
    plan = active_plan(getattr(session, "metadata_", None) if session is not None else None)
    plan = _with_real_fields(plan, tool_name, clean)
    params.update(with_markers(clean, lines))  # a masked value passed back runs with the real one
    reasons = uncovered(plan, tool_name, clean, _connection(tool_name, clean, context.project_config))
    if reasons:
        return _plan_refusal(tool_name, clean, plan, reasons)
    from ..change_preview import record_approval_ref
    from .chat_write_plan_match import match_plan_write

    match = match_plan_write(plan, tool_name, clean)
    if match.refusal is not None:
        return match.refusal
    if match.filled:
        # In place: the registry dispatches this very dict, so the write runs with the confirmed fields.
        params.clear()
        params.update(with_markers(match.fields, lines))
    admitted = getattr(context, "chat_write_plan_calls", None)
    if isinstance(admitted, set):
        mark = plan_call_mark(tool_name, params)
        admitted.add(mark)
        if match.filled:
            filled = getattr(context, "chat_write_plan_filled", None)
            if isinstance(filled, dict):
                filled[mark] = dict(match.filled)
    # A tool that audits its writes (custom REST) names the plan that admitted this one.
    record_approval_ref(context, tool_name, params, write_plan_id=(plan or {}).get("plan_id"))
    return None


def _with_real_fields(plan: dict[str, Any] | None, tool_name: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if plan is None:
        return None
    from ..secret_masking import real_fields, restore_masked_values

    canonical = tool_name
    writes = []
    for write in plan.get("writes") or []:
        if str(write.get("tool") or "") == canonical:
            restore_masked_values(params, write)
        writes.append({**write, "fields": real_fields(write)})
    return {**plan, "writes": writes}


def plan_call_mark(tool_name: str, params: Any) -> str:
    try:
        return f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
    except TypeError:
        return f"{tool_name}:{params}"


def created_values(result: Any) -> list[str]:
    if not isinstance(result, dict) or result.get("error"):
        return []
    found: list[str] = []
    for source in (result, *(value for value in result.values() if isinstance(value, dict))):
        for key in _CREATED_RESULT_KEYS:
            found.extend(_values(source.get(key)))
    return list(dict.fromkeys(found))


async def record_plan_created(tool_name: str, params: dict[str, Any], result: Any,
                              context: Any) -> dict[str, Any] | None:
    admitted = getattr(context, "chat_write_plan_calls", None)
    mark = plan_call_mark(tool_name, params)
    if not isinstance(admitted, set) or mark not in admitted:
        return None
    admitted.discard(mark)
    filled = (getattr(context, "chat_write_plan_filled", None) or {}).pop(mark, None)
    from ..secret_masking import masked

    note = {"filled_from_plan": masked(filled) if filled else filled,
            "note": "The call left these confirmed fields out; they were written as the plan says."} if filled else None
    values = created_values(result)
    session = await _session(getattr(context, "db", None), getattr(context, "session_id", None))
    if not values or session is None:
        return note
    metadata = dict(session.metadata_ or {})
    plan = active_plan(metadata)
    if plan is None:
        return note
    plan = dict(plan)
    plan["created"] = list(dict.fromkeys([*(plan.get("created") or []), *values]))
    metadata[PLAN_METADATA_KEY] = plan
    session.metadata_ = metadata
    await context.db.flush()
    return note


async def activate_confirmed_plan(db: Any, *, session: Any, approval_id: str, confirmed_by: str) -> bool:
    from sqlalchemy import select

    from ...models import ChangePreview

    rows = (await db.execute(select(ChangePreview.preview_json).where(ChangePreview.approval_id == approval_id,
                                                                       ChangePreview.tool_name == PROPOSE_WRITE_PLAN)
                             )).scalars().all()
    for preview_json in rows:
        try:
            proposal = json.loads(preview_json or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(proposal, dict) or proposal.get("kind") != PLAN_KIND:
            continue
        metadata = dict(session.metadata_ or {})
        current = metadata.get(PLAN_METADATA_KEY) if isinstance(metadata.get(PLAN_METADATA_KEY), dict) else None
        metadata[PLAN_METADATA_KEY] = merged_plan(current, {**proposal, "approval_id": approval_id},
                                                  confirmed_by=confirmed_by)
        session.metadata_ = metadata
        return True
    return False


def _write_call(write: dict[str, Any]) -> str:
    return f"{write.get('tool')} {json.dumps(write.get('fields') or {}, sort_keys=True, default=str)}"


def confirmed_plan_note(metadata: dict[str, Any] | None) -> str | None:
    plan = active_plan(metadata)
    if plan is None:
        return None
    lines = [f"The person has confirmed the write plan {plan.get('plan_id')} for this request. Perform its writes now: "
             "call their tools directly as your first step, with the confirmed fields (they already hold what the "
             f"earlier lookups found, so do not search again); do not call {PROPOSE_WRITE_PLAN} again for them (only "
             "for a further write the plan does not name). Confirmed writes:"]
    lines.extend(f"- {_write_call(write)}" for write in plan.get("writes") or [])
    created = [str(value) for value in plan.get("created") or []]
    if created:
        lines.append(f"Already done by this plan (never repeat these writes): {', '.join(created)}.")
    lines.append("Report what each write's result says it did (key, type, link), not what you intended.")
    return "\n".join(lines)


def plan_covers_all(plan: dict[str, Any] | None, writes: Iterable[dict[str, Any]],
                    connections: Iterable[str]) -> bool:
    return plan is not None and all(not uncovered(plan, write.get("tool", ""), write.get("fields"), connection)
                                    for write, connection in zip(writes, connections, strict=True))


__all__ = ["CODE_AMENDMENT_REQUIRED", "CODE_PLAN_REQUIRED", "PLAN_KIND", "PLAN_METADATA_KEY", "PLAN_POLICY",
           "PROPOSE_WRITE_PLAN", "TARGET_PARAMS", "activate_confirmed_plan", "active_plan", "call_targets",
           "confirmed_plan_note", "created_values", "current_request", "is_chat_plan_write", "merged_plan",
           "new_plan_id", "plan_covers_all", "plan_decision", "plan_view", "record_plan_created", "trusted_for_chat",
           "trusted_skips_plan", "uncovered"]
