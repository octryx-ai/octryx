"""ServiceNow: named connections bound to tables.

Besides the preset's connection unit (target, auth mode, principal, OIDC options, secrets) a ServiceNow connection
carries how its instance is read (``services/servicenow_scripted.py``): the API style (the Table API or the
instance's Scripted REST API), the Scripted REST paths and their page size. They describe the instance an account
talks to, so they belong to the connection, not to a use: an instance without Table API access answers 403 to every
Table API read of the connection (its test, Knowledge sync, intake and tools alike). Use settings stay on the
connector entry and the uses: the table allowlist (the binding), the record limit (assignment groups, services,
filter mode) and work-note write-back (``servicenow_worknote_*``, a Workspace's work item workflow).
"""

from __future__ import annotations

from ...connector_test.visible_scopes import servicenow_tables
from ...servicenow_scripted import (
    API_STYLE_FIELD,
    API_STYLES,
    CHANGE_TABLE,
    DEFAULT_PAGE_SIZE,
    INCIDENT_TABLE,
    JOURNAL_PATH_FIELD,
    PAGE_SIZE_FIELD,
    PATH_FIELDS,
)
from ..descriptor import CASE_LOWER, UNSCOPED_DEFAULT, Allowlist, Binding, ConnectorDescriptor, Field
from ._preset_unit import preset_unit
from .atlassian import complete_unit

_IMPLICIT_TABLES = {"list_servicenow_incidents": "incident", "list_servicenow_changes": "change_request"}


# How the instance is read (see the module doc); validated at save by ``servicenow_scripted.config_problems``.
API_FIELDS = (
    Field(API_STYLE_FIELD, "API style", kind="select", options=API_STYLES),
    Field(PATH_FIELDS[INCIDENT_TABLE], "Incidents path", placeholder="/api/<namespace>/<api>/incidents"),
    Field(PATH_FIELDS[CHANGE_TABLE], "Changes path", placeholder="/api/<namespace>/<api>/changes"),
    Field(JOURNAL_PATH_FIELD, "Journal path", placeholder="/api/<namespace>/<api>/journal"),
    Field(PAGE_SIZE_FIELD, "Page size", kind="int", placeholder=str(DEFAULT_PAGE_SIZE)),
)


def _table_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    table = params.get("table")
    return ((table.strip() if isinstance(table, str) else "") or _IMPLICIT_TABLES.get(tool_name, ""),)


SERVICENOW = ConnectorDescriptor(
    connector="servicenow",
    label="ServiceNow",
    binding=Binding("table", "Tables", r"[A-Za-z0-9_]{1,80}", CASE_LOWER, "table_1, table_2"),
    fields=(*preset_unit("servicenow"), *API_FIELDS),
    usable_field="servicenow_url",
    request_keys=_table_keys,
    allowlist=Allowlist("servicenow_allowed_tables"),
    unscoped=UNSCOPED_DEFAULT,
    complete=complete_unit("servicenow"),
    form="servicenow_auth",
    visible_scopes=servicenow_tables,
)

__all__ = ["API_FIELDS", "SERVICENOW"]
