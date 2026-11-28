"""ServiceNow Scripted REST endpoints instead of the Table API (``servicenow_api_style``)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

API_STYLE_FIELD = "servicenow_api_style"
STYLE_TABLE = "table"
STYLE_SCRIPTED = "scripted"
API_STYLES = (STYLE_TABLE, STYLE_SCRIPTED)

INCIDENT_TABLE = "incident"
CHANGE_TABLE = "change_request"
PATH_FIELDS = {INCIDENT_TABLE: "servicenow_incidents_path", CHANGE_TABLE: "servicenow_changes_path"}
JOURNAL_PATH_FIELD = "servicenow_journal_path"
PAGE_SIZE_FIELD = "servicenow_page_size"
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
MAX_PATH_CHARS = 300
_LIST_KEY_HINTS = {INCIDENT_TABLE: "incidents", CHANGE_TABLE: "changes"}
SUMMARY_FIELDS = (
    "sys_id", "number", "short_description", "state", "priority", "assigned_to", "assignment_group", "opened_at",
)

CODE_TABLE_API_DISABLED = "servicenow_table_api_disabled"
TABLE_API_DISABLED_HINT = "This connection uses the customer's Scripted REST API; use the incident/change tools"
CODE_ENDPOINT_NOT_CONFIGURED = "servicenow_endpoint_not_configured"
CODE_HTTP_STATUS = "servicenow_endpoint_http_status"
CODE_EMPTY_ANSWER = "servicenow_endpoint_empty_answer"
CODE_UNEXPECTED_SHAPE = "servicenow_endpoint_unexpected_shape"
CODE_UNREACHABLE = "servicenow_endpoint_unreachable"
CODE_QUERY_UNSUPPORTED = "servicenow_query_unsupported"
MESSAGES = {
    CODE_TABLE_API_DISABLED: TABLE_API_DISABLED_HINT,
    CODE_ENDPOINT_NOT_CONFIGURED: "No Scripted REST path is configured for this record kind.",
    CODE_HTTP_STATUS: "The Scripted REST endpoint answered with an error status.",
    CODE_EMPTY_ANSWER: "The Scripted REST endpoint answered without content.",
    CODE_UNEXPECTED_SHAPE: "The Scripted REST endpoint answered without a single record list in 'result'.",
    CODE_UNREACHABLE: "The Scripted REST endpoint could not be reached.",
    CODE_QUERY_UNSUPPORTED: "A query filter is not supported by the Scripted REST endpoints; omit it.",
}

_PATH = re.compile(r"^/api/[A-Za-z0-9_.~/-]+$")


class ScriptedEndpointError(Exception):
    # Never a body or a value.

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        suffix = f" (HTTP {http_status})" if http_status is not None else ""
        super().__init__(f"{code}: {MESSAGES[code]}{suffix}")
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class ScriptedApi:
    paths: Mapping[str, str]  # table -> path, only the configured ones
    page_size: int = DEFAULT_PAGE_SIZE
    journal_path: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptedPage:
    records: list[dict[str, Any]]
    total: int | None


def _text(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


def api_style(config: Mapping[str, Any]) -> str:
    # An unknown value is returned as is (fail closed).
    return _text(config, API_STYLE_FIELD) or STYLE_TABLE


def path_problem(value: object) -> str | None:
    text = value if isinstance(value, str) else ""
    if not text or len(text) > MAX_PATH_CHARS or not _PATH.match(text) or ".." in text or "//" in text:
        return "must be a path that begins with /api/, without scheme, host, '..', query or fragment"
    return None


def _page_size(value: object) -> int | None:
    if value in (None, ""):
        return DEFAULT_PAGE_SIZE
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        return None
    return value


WORKNOTE_MODE_FIELD = "servicenow_worknote_mode"
WORKNOTE_PATH_FIELD = "servicenow_worknote_path"
WORKNOTE_OFF, WORKNOTE_SCRIPTED_POST, WORKNOTE_TABLE_API = "off", "scripted_post", "table_api"
WORKNOTE_MODES = (WORKNOTE_OFF, WORKNOTE_SCRIPTED_POST, WORKNOTE_TABLE_API)


def worknote_mode(config: Mapping[str, Any]) -> str:
    # An unknown value is returned as is.
    return _text(config, WORKNOTE_MODE_FIELD) or WORKNOTE_OFF


def worknote_problems(config: Mapping[str, Any]) -> list[str]:
    mode = worknote_mode(config)
    if mode not in WORKNOTE_MODES:
        return [f"{WORKNOTE_MODE_FIELD} must be one of: {', '.join(WORKNOTE_MODES)}"]
    path = _text(config, WORKNOTE_PATH_FIELD)
    if mode == WORKNOTE_SCRIPTED_POST and not path:
        return [f"needs: {WORKNOTE_PATH_FIELD}"]
    if path and (problem := path_problem(path)):
        return [f"{WORKNOTE_PATH_FIELD} {problem}"]
    return []


def config_problems(config: Mapping[str, Any]) -> list[str]:
    # Names and fixed text only.
    style = api_style(config)
    if style not in API_STYLES:
        return [f"{API_STYLE_FIELD} must be one of: {', '.join(API_STYLES)}", *worknote_problems(config)]
    if worknote_problems(config):
        return worknote_problems(config)
    if style == STYLE_TABLE:
        return []
    problems = []
    configured = [field for field in (*PATH_FIELDS.values(), JOURNAL_PATH_FIELD) if _text(config, field)]
    if not any(_text(config, field) for field in PATH_FIELDS.values()):
        problems.append(f"needs: {' or '.join(PATH_FIELDS.values())}")
    problems += [f"{field} {problem}" for field in configured if (problem := path_problem(config.get(field)))]
    if _page_size(config.get(PAGE_SIZE_FIELD)) is None:
        problems.append(f"{PAGE_SIZE_FIELD} must be an integer from 1 to {MAX_PAGE_SIZE}")
    return problems


def scripted_api(config: Mapping[str, Any]) -> ScriptedApi | None:
    if api_style(config) == STYLE_TABLE:
        return None
    if config_problems(config):
        raise ScriptedEndpointError(CODE_ENDPOINT_NOT_CONFIGURED)
    paths = {table: _text(config, field) for table, field in PATH_FIELDS.items() if _text(config, field)}
    journal = _text(config, JOURNAL_PATH_FIELD) or None
    return ScriptedApi(paths=paths, page_size=_page_size(config.get(PAGE_SIZE_FIELD)) or DEFAULT_PAGE_SIZE,
                       journal_path=journal)


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_page(payload: object, table: str) -> ScriptedPage:
    if payload in (None, "", {}, []):
        raise ScriptedEndpointError(CODE_EMPTY_ANSWER)
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, list):
        records, total = result, None
    elif isinstance(result, dict):
        list_keys = [key for key, value in result.items() if isinstance(value, list)]
        hint = _LIST_KEY_HINTS.get(table)
        if len(list_keys) == 1:
            key = list_keys[0]
        elif hint in list_keys:
            key = hint
        else:
            raise ScriptedEndpointError(CODE_UNEXPECTED_SHAPE)
        records, total = result[key], _count(result.get("total"))
    else:
        raise ScriptedEndpointError(CODE_UNEXPECTED_SHAPE)
    if not all(isinstance(record, dict) for record in records):
        raise ScriptedEndpointError(CODE_UNEXPECTED_SHAPE)
    return ScriptedPage(records=list(records), total=total)


def _display(value: object) -> object:
    if isinstance(value, dict) and ("display_value" in value or "value" in value):
        return value.get("display_value", value.get("value"))
    return value


def record_link(base_url: str, table: str, sys_id: object) -> str | None:
    if not isinstance(sys_id, str) or not sys_id.isalnum():
        return None
    return f"{base_url.rstrip('/')}/nav_to.do?uri={quote(f'{table}.do?sys_id={sys_id}', safe='./')}"


def normalize_record(record: Mapping[str, Any], table: str, base_url: str) -> dict[str, Any]:
    normalized = {key: _display(record.get(key)) for key in SUMMARY_FIELDS}
    normalized.update({key: _display(value) for key, value in record.items() if key not in normalized})
    normalized["table"] = table
    normalized["url"] = record_link(base_url, table, normalized.get("sys_id"))
    return normalized


__all__ = [
    "API_STYLES",
    "API_STYLE_FIELD",
    "CHANGE_TABLE",
    "CODE_TABLE_API_DISABLED",
    "INCIDENT_TABLE",
    "MAX_PAGE_SIZE",
    "PATH_FIELDS",
    "STYLE_SCRIPTED",
    "STYLE_TABLE",
    "TABLE_API_DISABLED_HINT",
    "ScriptedApi",
    "ScriptedEndpointError",
    "ScriptedPage",
    "api_style",
    "config_problems",
    "normalize_record",
    "parse_page",
    "path_problem",
    "record_link",
    "scripted_api",
]
