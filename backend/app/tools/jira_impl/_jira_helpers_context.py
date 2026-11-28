"""Jira context and release-date helpers."""

import re
from datetime import datetime

from app.services.connector_auth.atlassian_modes import JIRA
from app.tools.context import ToolContext

from ...services.connector_auth.atlassian import auth_headers, request_auth
from ._jira_relative_dates import infer_relative_release_date_from_message


def _jira_base_url(context: ToolContext) -> str:
    return str(context.project_config.get("jira_url") or "").strip().rstrip("/")


def _jira_allowed_projects(context: ToolContext) -> list[str] | None:
    raw = context.project_config.get("jira_allowed_projects")
    if raw is None:
        return None
    if isinstance(raw, list):
        keys = [str(k).strip().upper() for k in raw if str(k).strip()]
        return keys if keys else None
    if isinstance(raw, str):
        keys = [k.strip().upper() for k in raw.replace(",", " ").split() if k.strip()]
        return keys if keys else None
    return None


def _jira_check_project_allowed(ticket_id: str, allowed: list[str] | None) -> str | None:
    if not allowed:
        return None
    # ticket_id looks like "ACME-123" — project key is everything before the last hyphen+digits
    match = re.match(r"^([A-Z][A-Z0-9_]*)[-_]\d+$", ticket_id.strip().upper())
    if not match:
        return f"Cannot determine project key from ticket ID '{ticket_id}'"
    project_key = match.group(1)
    if project_key not in allowed:
        return f"Ticket '{ticket_id}' belongs to project '{project_key}' which is not in the allowed list: {allowed}"
    return None


def _jira_auth_headers(context: ToolContext) -> dict[str, str]:
    return auth_headers(JIRA, context.project_config)


def _jira_http(context: ToolContext) -> dict:
    return {"timeout": 30, "follow_redirects": True, "auth": request_auth(JIRA, context.project_config)}


def _jira_default_project_key(context: ToolContext) -> str | None:
    allowed = _jira_allowed_projects(context)
    if allowed and len(allowed) == 1:
        return allowed[0]
    return None


def _infer_relative_release_date(context: ToolContext) -> str:
    message = str(context.current_user_message or "").strip().lower()
    if not message:
        return ""

    now = datetime.now().astimezone().date()
    return infer_relative_release_date_from_message(message, today=now)


def _normalize_requested_release_date(raw_release_date: str, context: ToolContext) -> str:
    explicit_date = str(raw_release_date or "").strip()
    inferred_date = _infer_relative_release_date(context)
    if not inferred_date:
        return explicit_date
    if not explicit_date:
        return inferred_date
    today = datetime.now().astimezone().date().isoformat()
    if explicit_date == today:
        return inferred_date
    return explicit_date
