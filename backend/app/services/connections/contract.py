"""Fixed words and refusals of the connections API."""

from __future__ import annotations

from fastapi import HTTPException

STATE_OK = "ok"
STATE_FAILING = "failing"
STATE_UNTESTED = "untested"
STATE_DISABLED = "disabled"
STATES = (STATE_OK, STATE_FAILING, STATE_UNTESTED, STATE_DISABLED)

AVAILABLE_ALL = "all"
AVAILABLE_SELECTED = "selected"
AVAILABLE_IN = (AVAILABLE_ALL, AVAILABLE_SELECTED)
OWNER_PLATFORM = "platform"
OWNER_WORKSPACE = "workspace"
LEVELS = ("off", "read", "write")
DEFAULT_LEVEL = "read"

USE_KNOWLEDGE = "knowledge"
USE_TICKETS = "tickets"
USE_AGENT_TOOLS = "agent_tools"
USE_REPOSITORIES = "repositories"
USE_ACCESS = "access"

ORIGIN_CONNECTIONS_API = "connections_api"
MAX_NAME_CHARS = 64

CODE_NOT_FOUND = "connection_not_found"
CODE_TYPE_UNKNOWN = "connection_type_unknown"
CODE_NAME_INVALID = "connection_name_invalid"
CODE_NAME_TAKEN = "connection_name_taken"
CODE_FIELD_INVALID = "connection_field_invalid"
CODE_IN_USE = "connection_in_use"
CODE_TEST_UNAVAILABLE = "connection_test_unavailable"
CODE_PLATFORM_ADMIN_REQUIRED = "platform_admin_required"
CODE_WORKSPACE_ADMIN_REQUIRED = "workspace_admin_required"
CODE_SCOPE_OUTSIDE = "scope_outside_connection"
CODE_SCHEDULE_CRON_INVALID = "schedule_cron_invalid"
CODE_SCHEDULE_INVALID = "schedule_invalid"
CODE_STATUS_UNKNOWN = "status_unknown"
CODE_USE_NOT_LINKED = "use_not_linked"
CODE_USE_SPANS_WORKSPACES = "use_spans_workspaces"
CODE_WRITE_BACK_ON_WORKFLOW = "write_back_on_workflow"


def refusal(status: int, code: str, message: str, field: str | None = None) -> HTTPException:
    detail = {"code": code, "message": message}
    if field is not None:
        detail["field"] = field
    return HTTPException(status_code=status, detail=detail)


def not_found() -> HTTPException:
    return refusal(404, CODE_NOT_FOUND, "The connection does not exist or is not visible to you.")


def invalid(field: str, message: str, code: str = CODE_FIELD_INVALID) -> HTTPException:
    return refusal(422, code, message, field)


__all__ = [name for name in dir() if name.isupper() or name in ("invalid", "not_found", "refusal")]
