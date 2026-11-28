"""Confluence and Jira: named connections bound to space keys and project keys."""

from __future__ import annotations

import re
from typing import Any

from app.services.connector_auth.atlassian_modes import AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import validate_auth_config

from ...connector_test.visible_scopes import confluence_spaces, jira_projects
from ...tool_config.connection_fields import auth_mode_fields, target_fields
from ..descriptor import (
    CASE_UPPER,
    UNSCOPED_DEFAULT,
    Allowlist,
    Binding,
    ConnectorDescriptor,
    UnitIncompleteError,
)
from ._preset_unit import preset_unit

CODE_AUTH_INVALID = "atlassian_auth_invalid"
FORM_ATLASSIAN = "atlassian_auth"
_ISSUE_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)-\d+$")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def issue_project(value: object) -> str | None:
    match = _ISSUE_KEY.fullmatch(_text(value))
    return match.group(1) if match else None


def complete_unit(tool_name: str):
    def check(config: dict) -> None:
        url_field, mode_field = target_fields(tool_name)[0], auth_mode_fields(tool_name)[0]
        for required in (url_field, mode_field):
            if config.get(required) in (None, "", [], {}):
                raise UnitIncompleteError(CODE_AUTH_INVALID, f"An own connection needs {required}.")
        try:
            validate_auth_config(tool_name, config)
        except AtlassianAuthConfigError as exc:
            raise UnitIncompleteError(exc.code, str(exc)) from None

    return check


def _confluence_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    return (_text(params.get("space_key")),)


def _jira_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    raw = [_text(params.get("project_key")), issue_project(params.get("ticket_id")) or ""]
    ticket_ids = params.get("ticket_ids")
    if isinstance(ticket_ids, list):
        raw.extend(issue_project(item) or "" for item in ticket_ids)
    return tuple(raw)


def _jira_result_key(item: Any) -> str | None:
    return issue_project(item.get("key")) if isinstance(item, dict) else None


CONFLUENCE = ConnectorDescriptor(
    connector="confluence",
    label="Confluence",
    binding=Binding("space", "Spaces", r"~?[A-Za-z0-9_]{1,64}", CASE_UPPER, "SPACE1, SPACE2"),  # Source Sync's rule
    fields=preset_unit("confluence"),
    usable_field="confluence_url",
    request_keys=_confluence_keys,
    allowlist=Allowlist("confluence_allowed_spaces", serves_unlisted=False, single_key_field="confluence_space_key"),
    unscoped=UNSCOPED_DEFAULT,
    fan_out_tools=frozenset({"search_confluence"}),
    named_drops=("confluence_space_key",),
    complete=complete_unit("confluence"),
    form=FORM_ATLASSIAN,
    visible_scopes=confluence_spaces,
)

JIRA = ConnectorDescriptor(
    connector="jira",
    label="Jira",
    binding=Binding("project", "Projects", r"[A-Za-z][A-Za-z0-9_]{0,63}", CASE_UPPER, "PROJ1, PROJ2"),
    fields=preset_unit("jira"),
    usable_field="jira_url",
    request_keys=_jira_keys,
    allowlist=Allowlist("jira_allowed_projects"),
    unscoped=UNSCOPED_DEFAULT,
    fan_out_tools=frozenset({"search_jira_tickets"}),
    # An unrestricted default never reports an issue of a bound project (read by its own account).
    result_key=_jira_result_key,
    complete=complete_unit("jira"),
    form=FORM_ATLASSIAN,
    visible_scopes=jira_projects,
)

__all__ = ["CONFLUENCE", "JIRA", "complete_unit", "issue_project"]
