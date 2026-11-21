"""Structured thread context extraction and persistence helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, ThreadContext
from ....services.content_security.untrusted_fence import untrusted_section
from ....services.prompt_catalog import bound_prompt_set, render_prompt
from ....services.prompt_catalog.out_of_turn import render_prompt_for_scope
from ..runtime.trace_runtime import compact_trace_value


def _clean_text(value: str | None, *, limit: int = 320) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _extract_open_questions(assistant_content: str) -> list[str]:
    content = str(assistant_content or "").strip()
    if not content:
        return []
    if content.startswith("HUMAN_INPUT_REQUIRED:"):
        return [_clean_text(content.removeprefix("HUMAN_INPUT_REQUIRED:").strip(), limit=500)]
    questions: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.endswith("?"):
            questions.append(stripped)
    return _dedupe_strings(questions)


def _extract_errors(
    *,
    tool_trace: list[dict[str, Any]] | None,
    raw_output: dict[str, Any] | None,
    assistant_content: str,
) -> list[str]:
    errors: list[str] = []
    payload = raw_output or {}
    if payload.get("error"):
        errors.append(str(payload["error"]))
    for item in tool_trace or []:
        result = item.get("result") if isinstance(item, dict) else None
        if isinstance(result, dict) and result.get("error"):
            tool_name = str(item.get("tool_name") or "tool")
            errors.append(f"{tool_name}: {result['error']}")
    content = str(assistant_content or "").strip()
    if content.startswith("Agent error:"):
        errors.append(content.removeprefix("Agent error:").strip())
    return _dedupe_strings(errors)


def _extract_constraints(context_snapshot: dict[str, Any] | None) -> list[str]:
    snapshot = context_snapshot or {}
    constraints: list[str] = []
    agent_info = snapshot.get("agent") if isinstance(snapshot.get("agent"), dict) else {}
    agent_type = str(agent_info.get("type") or "").strip()
    if agent_type:
        constraints.append(f"Agent mode: {agent_type}")
    context_plan = snapshot.get("context_plan") if isinstance(snapshot.get("context_plan"), dict) else {}
    if context_plan.get("route_reason"):
        constraints.append(f"Route: {context_plan['route_reason']}")
    if context_plan.get("domains"):
        constraints.append("Domains: " + ", ".join(str(item) for item in context_plan["domains"][:5]))
    current_step = snapshot.get("current_step") if isinstance(snapshot.get("current_step"), dict) else {}
    if current_step.get("name"):
        constraints.append(f"Current step: {current_step['name']}")
    return _dedupe_strings(constraints)


def _extract_entities(
    *,
    context_snapshot: dict[str, Any] | None,
    tool_trace: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    snapshot = context_snapshot or {}
    entities: dict[str, Any] = {}
    context_plan = snapshot.get("context_plan") if isinstance(snapshot.get("context_plan"), dict) else {}
    domains = [str(item) for item in (context_plan.get("domains") or []) if str(item).strip()]
    request_analysis = snapshot.get("request_analysis") if isinstance(snapshot.get("request_analysis"), dict) else {}
    request_text = " ".join(
        str(request_analysis.get(key) or "")
        for key in ("canonical_message", "original_message", "user_request", "message")
    ).casefold()
    domain_aliases = {
        "bitbucket": ("bitbucket", "repository", "repositories", "commit", "pull request", "pr"),
        "confluence": ("confluence", "wiki", "page", "pages"),
        "jira": ("jira", "ticket", "issue", "sprint", "release"),
        "knowledge": ("knowledge", "kb"),
    }
    mentioned_domains = [
        domain
        for domain in domains
        if any(alias in request_text for alias in domain_aliases.get(domain.casefold(), (domain.casefold(),)))
    ]
    if mentioned_domains:
        domains = mentioned_domains
    if domains:
        entities["domains"] = domains
    agent_info = snapshot.get("agent") if isinstance(snapshot.get("agent"), dict) else {}
    if agent_info.get("name"):
        entities["agent_name"] = str(agent_info["name"])
    worker_type = str(snapshot.get("worker_type") or "").strip()
    if worker_type:
        entities["worker_type"] = worker_type
    for key in ("ticket", "repository", "target"):
        value = snapshot.get(key)
        if isinstance(value, dict) and value:
            entities[key] = compact_trace_value(value)
    repo_path = str(snapshot.get("repo_path") or "").strip()
    if repo_path:
        entities["repo_path"] = repo_path
    tool_names = [str(item.get("tool_name") or "").strip() for item in (tool_trace or []) if isinstance(item, dict)]
    tool_names = [name for name in tool_names if name]
    if tool_names:
        entities["last_tool_names"] = tool_names[:8]
    return entities


def render_thread_context_for_prompt(context_json: dict[str, Any] | None) -> str:
    context = context_json or {}
    lines: list[str] = []
    if context.get("goal"):
        lines.append(f"Goal: {context['goal']}")
    if context.get("current_task"):
        lines.append(f"Current task: {context['current_task']}")
    constraints = context.get("constraints") or []
    if constraints:
        lines.append("Constraints:")
        lines.extend(f"- {item}" for item in constraints[:4])
    open_questions = context.get("open_questions") or []
    if open_questions:
        lines.append("Open questions:")
        lines.extend(f"- {item}" for item in open_questions[:4])
    errors = context.get("last_known_errors") or []
    if errors:
        # Tool errors quote external systems and land in a system message: an untrusted block.
        lines.append("Latest known errors:")
        lines.append(untrusted_section("tool errors", "\n".join(f"- {item}" for item in errors[:4]),
                                       source="tool results"))
    stuck_loop = context.get("stuck_loop_detector") if isinstance(context.get("stuck_loop_detector"), dict) else {}
    if stuck_loop:
        lines.append(
            "Loop detector: " + str(stuck_loop.get("kind") or "unknown") + " - " + str(stuck_loop.get("message") or "")
        )
        if stuck_loop.get("recommended_action"):
            lines.append(f"Loop recovery hint: {stuck_loop['recommended_action']}")
    loop_recovery = context.get("loop_recovery") if isinstance(context.get("loop_recovery"), dict) else {}
    if loop_recovery and loop_recovery.get("action"):
        lines.append(f"Loop recovery action: {loop_recovery['action']}")
    entities = context.get("active_entities") or {}
    domains = entities.get("domains") if isinstance(entities, dict) else []
    if domains:
        lines.append("Active domains: " + ", ".join(str(item) for item in domains[:5]))
    if context.get("next_expected_action"):
        lines.append(f"Next expected action: {context['next_expected_action']}")
    tdd_cycle = context.get("tdd_cycle") if isinstance(context.get("tdd_cycle"), dict) else {}
    if tdd_cycle:
        phases = tdd_cycle.get("phases") if isinstance(tdd_cycle.get("phases"), list) else []
        phase_index = int(tdd_cycle.get("phase_index") or 0)
        if phases:
            current_phase = phases[max(0, min(phase_index, len(phases) - 1))]
            lines.append(
                f"TDD cycle phase: {current_phase.get('title') or current_phase.get('name') or 'unknown'} "
                f"({phase_index + 1}/{len(phases)})"
            )
    return "\n".join(lines).strip()


async def _render_next_action(db: AsyncSession, session_id: str, key: str) -> str:
    """The stored next-action nudge: the turn's prompt set, else the session Workspace's (no turn bound)."""
    if bound_prompt_set() is not None:
        return render_prompt(key)
    workspace_id = (await db.execute(select(Session.project_id).where(Session.id == session_id))).scalar_one_or_none()
    return await render_prompt_for_scope(db, key, workspace_id=workspace_id)


def _next_action_key(
    *,
    open_questions: list[str],
    errors: list[str],
    tool_trace: list[dict[str, Any]] | None,
    assistant_content: str,
) -> str:
    if open_questions:
        return "tool_guard.thread.next_clarification"
    if errors:
        return "tool_guard.thread.next_error"
    if tool_trace:
        return "tool_guard.thread.next_tool_results"
    if assistant_content:
        return "tool_guard.thread.next_continue"
    return ""


def _store_thread_context(
    db: AsyncSession,
    existing: ThreadContext | None,
    *,
    session_id: str,
    context_json: dict[str, Any],
    derived_from_message_id: str | None,
) -> ThreadContext:
    """Bump the existing row to a new version, or add the session's first one."""
    if existing:
        existing.version = int(existing.version or 0) + 1
        existing.context_json = context_json
        existing.derived_from_message_id = derived_from_message_id
        return existing

    thread_context = ThreadContext(
        session_id=session_id,
        version=1,
        context_json=context_json,
        derived_from_message_id=derived_from_message_id,
    )
    db.add(thread_context)
    return thread_context


async def upsert_thread_context(
    *,
    db: AsyncSession,
    session_id: str,
    derived_from_message_id: str | None,
    current_user_message: str,
    assistant_content: str,
    context_snapshot: dict[str, Any] | None,
    tool_trace: list[dict[str, Any]] | None = None,
    raw_output: dict[str, Any] | None = None,
) -> ThreadContext:
    existing = (
        await db.execute(select(ThreadContext).where(ThreadContext.session_id == session_id))
    ).scalar_one_or_none()
    existing_context = dict(existing.context_json or {}) if existing and isinstance(existing.context_json, dict) else {}

    goal = existing_context.get("goal") or _clean_text(current_user_message, limit=280)
    current_task = _clean_text(current_user_message, limit=320)
    open_questions = _extract_open_questions(assistant_content)
    errors = _extract_errors(tool_trace=tool_trace, raw_output=raw_output, assistant_content=assistant_content)
    constraints = _extract_constraints(context_snapshot)
    active_entities = _extract_entities(context_snapshot=context_snapshot, tool_trace=tool_trace)

    next_action_key = _next_action_key(
        open_questions=open_questions, errors=errors, tool_trace=tool_trace, assistant_content=assistant_content
    )
    next_expected_action = await _render_next_action(db, session_id, next_action_key) if next_action_key else ""

    context_json = {
        "goal": goal,
        "current_task": current_task,
        "constraints": constraints,
        "decisions": existing_context.get("decisions") or [],
        "open_questions": open_questions,
        "active_entities": active_entities,
        "current_repo_state": active_entities.get("repository") or {},
        "current_ticket_state": active_entities.get("ticket") or {},
        "last_known_errors": errors,
        "next_expected_action": next_expected_action,
    }
    # The turn's loop state wins; without it the thread keeps the last recorded one.
    for key in ("tdd_cycle", "stuck_loop_detector", "loop_recovery"):
        value = (
            (context_snapshot or {}).get(key)
            if isinstance((context_snapshot or {}).get(key), dict)
            else existing_context.get(key)
        )
        if isinstance(value, dict) and value:
            context_json[key] = compact_trace_value(value)
    return _store_thread_context(
        db,
        existing,
        session_id=session_id,
        context_json=compact_trace_value(context_json),
        derived_from_message_id=derived_from_message_id,
    )
