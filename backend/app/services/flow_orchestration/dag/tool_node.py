"""Tool and retrieval nodes: argument rendering, the tool call and the context passed downstream."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from ....tools.context import ToolContext
from ....tools.registry import execute_tool_with_plugins
from ...flow_runtime_governance import FlowRuntimeLimits, FlowRuntimeUsage, record_tool_call_within_limits
from ...runtime_failure_errors import FlowInputContractError, tool_result_failure_error
from .evidence import _normalize_tool_result
from .paths import _render_template_value


async def _execute_tool_node(
    *,
    db: AsyncSession,
    node_id: str,
    config: dict[str, Any],
    input_snapshot: dict[str, Any],
    initial_input: dict[str, Any],
    project_id: str | None,
    project_config: dict[str, Any],
    user_id: str,
    session_id: str,
    limits: FlowRuntimeLimits,
    usage: FlowRuntimeUsage,
    run_capability: dict[str, Any],
) -> dict[str, Any]:
    tool_name = str(config.get("tool") or config.get("tool_name") or "").strip()
    if not tool_name:
        raise FlowInputContractError(f"Tool node {node_id} is missing config.tool")
    record_tool_call_within_limits(usage=usage, limits=limits)
    if "arguments" in config:
        raw_params = config.get("arguments")
    elif "parameters" in config:
        raw_params = config.get("parameters")
    elif "arguments" in input_snapshot:
        raw_params = input_snapshot.get("arguments")
    else:
        raw_params = input_snapshot
    params = _render_template_value(raw_params, {**initial_input, **input_snapshot})
    if not isinstance(params, dict):
        raise FlowInputContractError(f"Tool node {node_id} arguments must be an object")
    context = ToolContext(
        user_id=user_id,
        project_ids=[project_id] if project_id else [],
        roles=[],
        session_id=session_id,
        project_config=project_config,
        db=db,
        run_capability=run_capability,
    )
    result = await execute_tool_with_plugins(tool_name, params, context)
    result_payload = _normalize_tool_result(result)
    if result_payload.get("error"):
        raise tool_result_failure_error(result_payload)
    return {
        "tool": tool_name,
        "result": result_payload,
        **_flow_context_from_tool_result(
            tool_name,
            result_payload,
            input_snapshot=input_snapshot,
            initial_input=initial_input,
            params=params,
        ),
    }


def _flow_context_from_tool_result(
    tool_name: str,
    result_payload: dict[str, Any],
    *,
    input_snapshot: dict[str, Any],
    initial_input: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in ("request", "subject_hint"):
        value = initial_input.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    for key in ("jira_username", "bitbucket_username"):
        value = input_snapshot.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    for key in ("release_name", "release_id", "release_date", "release_project_key", "release_status"):
        value = input_snapshot.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
    aliases = input_snapshot.get("person_aliases")
    if isinstance(aliases, list):
        propagated_aliases = _person_aliases_from_values(*aliases)
        if propagated_aliases:
            context["person_aliases"] = propagated_aliases

    if tool_name == "search_jira_users":
        users = result_payload.get("users") if isinstance(result_payload.get("users"), list) else []
        first_user = next((user for user in users if isinstance(user, dict)), {})
        aliases = _person_aliases_from_values(
            context.get("subject_hint"),
            first_user.get("name"),
            first_user.get("display_name"),
            first_user.get("email"),
            first_user.get("key"),
        )
        if first_user.get("name"):
            context["jira_username"] = str(first_user["name"]).strip()
        if aliases:
            context["person_aliases"] = aliases
    elif tool_name == "search_bitbucket_users":
        users = result_payload.get("users") if isinstance(result_payload.get("users"), list) else []
        first_user = next((user for user in users if isinstance(user, dict)), {})
        aliases = _person_aliases_from_values(
            context.get("subject_hint"),
            first_user.get("name"),
            first_user.get("display_name"),
            first_user.get("email_address"),
            params.get("query"),
        )
        if first_user.get("name"):
            context["bitbucket_username"] = str(first_user["name"]).strip()
        if aliases:
            context["person_aliases"] = aliases
    elif tool_name == "list_jira_versions":
        release_context = _next_jira_release_context(result_payload)
        if release_context:
            context.update(release_context)
    return context


def _next_jira_release_context(result_payload: dict[str, Any]) -> dict[str, Any]:
    versions = [item for item in result_payload.get("versions") or [] if isinstance(item, dict)]
    candidates = [item for item in versions if not item.get("released") and not item.get("archived")]
    if not candidates:
        return {}

    today = utc_now().date()
    dated_upcoming = [
        item
        for item in candidates
        if _parse_date(str(item.get("release_date") or "")) is not None
        and _parse_date(str(item.get("release_date") or "")) >= today
    ]
    if dated_upcoming:
        selected = min(dated_upcoming, key=lambda item: _parse_date(str(item.get("release_date") or "")) or date.max)
    else:
        dated_any = [item for item in candidates if _parse_date(str(item.get("release_date") or "")) is not None]
        selected = (
            min(dated_any, key=lambda item: _parse_date(str(item.get("release_date") or "")) or date.max)
            if dated_any
            else candidates[0]
        )

    name = str(selected.get("name") or "").strip()
    if not name:
        return {}
    release_date = str(selected.get("release_date") or "").strip()
    project_key = str(selected.get("project_key") or result_payload.get("project_key") or "").strip()
    release_id = str(selected.get("id") or "").strip()
    return {
        "release_name": name,
        "release_id": release_id,
        "release_date": release_date,
        "release_project_key": project_key,
        "release_status": "unreleased",
    }


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _person_aliases_from_values(*values: Any) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text.lower() in seen:
            continue
        aliases.append(text)
        seen.add(text.lower())
    return aliases
