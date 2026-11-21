"""Custom REST's record-level part of the shared intake pipeline (``intake/pipeline``).

A record becomes a Work item through the intake's field mapping (dotted paths, ``config``). What it refuses or drops,
and why:

- a record without a stable key (``key``; ``id`` when mapped) is ``skipped_invalid``: an item imported under a
  made-up key would be imported again on the next run and could never be closed or written back;
- texts are bounded to the Work item's columns like the other intakes (title 500, description 20000, keys 220);
- the reporter must be an identifier (an e-mail address, a user name or id): a person is matched by identifier only
  (``workflow_runs.responsible``), so a display name ("Rita Muster") is not kept as the reporter;
- a link is kept only as an ``http(s)`` URL.

The records are third-party content: where an item reaches a model (the analysis prompt) it goes inside the shared
untrusted fence (``work_item_analysis.prompt``), like every other source's.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkItem, WorkItemSyncConfig
from ...rest_connector.response import get_path
from ..intake.pipeline import text
from ..intake.protocol import Listed
from ..jira_values import parse_datetime
from .config import LABEL, SOURCE_TYPE, intake_of_row, is_closed, mapped_state
from .listing import IntakeCallContext, acting_role, read_pages, resolve_list

SYNC_AUDIT_ACTION = "secure_work.custom_rest_intake.synced"
_IDENTIFIER_KEYS = ("email", "emailAddress", "username", "user_name", "login", "name", "id")
_IDENTIFIER_RE = re.compile(r"^[^\s]{1,220}$")


def _scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in ("value", "name", "key", "id"):
            if isinstance(value.get(key), str | int):
                return value[key]
        return None
    return value if isinstance(value, str | int | float) and not isinstance(value, bool) else None


def identifier(value: Any) -> str | None:
    """An identifier of a person (no whitespace: an e-mail, user name or id), else ``None``."""
    if isinstance(value, Mapping):
        value = next((value[key] for key in _IDENTIFIER_KEYS if isinstance(value.get(key), str | int)), None)
    candidate = text(value, 220) if isinstance(value, str | int) and not isinstance(value, bool) else None
    return candidate if candidate and _IDENTIFIER_RE.fullmatch(candidate) else None


def _url(value: Any) -> str | None:
    link = text(_scalar(value), 2000)
    return link if link and link.lower().startswith(("https://", "http://")) else None


def _labels(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else str(value).split(",") if isinstance(value, str) else []
    labels = [text(_scalar(entry), 120) for entry in raw]
    return list(dict.fromkeys(label for label in labels if label))


class CustomRestRecords:
    """The :class:`~..intake.protocol.RecordSource` of a Custom REST list operation."""

    source_type = SOURCE_TYPE
    label = LABEL
    sync_audit_action = SYNC_AUDIT_ACTION

    def intake_of(self, row: WorkItemSyncConfig) -> dict[str, Any]:
        return intake_of_row(row)

    async def read(self, db: AsyncSession, row: WorkItemSyncConfig, intake: Mapping[str, Any], *, dry_run: bool,
                   user: User) -> Listed:
        definition, operation = await resolve_list(db, row.project_id, intake["definition"], intake["operation"])
        role = acting_role(operation, intake["role"], row.project_id)
        context = IntakeCallContext(user_id=user.id, project_id=row.project_id, db=db, acting_role=role)
        page = await read_pages(db, definition=definition, operation=operation, context=context,
                                arguments=intake["arguments"], max_items=intake["max_items"],
                                max_pages=intake["max_pages"])
        group = operation.op_key
        return Listed(entries=[(group, record) for record in page.records], complete=page.complete,
                      instance=definition.key, detail={"role": role, "pages": page.pages, "operation": group},
                      counts={"dropped_out_of_scope": page.dropped})

    def payload(self, row: WorkItemSyncConfig, listed: Listed, group: str, record: Mapping[str, Any],
                intake: Mapping[str, Any]) -> dict[str, Any] | None:
        fields = intake["fields"]

        def at(name: str) -> Any:
            return get_path(record, fields[name]) if fields.get(name) else None

        key = text(_scalar(at("key")), 220)
        source_id = text(_scalar(at("id")), 220) if fields.get("id") else key
        if key is None or source_id is None:
            return None
        status = text(_scalar(at("status")), 120)
        work_state, state_source = mapped_state(status, intake)
        return {
            "project_id": row.project_id, "sync_config_id": row.id, "source_type": SOURCE_TYPE,
            "source_instance": listed.instance, "source_id": source_id, "source_project_key": listed.instance,
            "source_key": key, "source_url": _url(at("url")), "issue_type": text(_scalar(at("type")), 120),
            "title": text(_scalar(at("title")), 500) or key,
            "description": text(_scalar(at("description")), 20000), "source_status": status,
            "priority": text(_scalar(at("priority")), 120), "assignee": identifier(at("assignee")),
            "reporter": identifier(at("reporter")), "parent_key": text(_scalar(at("parent")), 220),
            "labels_json": _labels(at("labels")),
            "source_created_at": parse_datetime(_scalar(at("created_at"))),
            "last_source_updated_at": parse_datetime(_scalar(at("updated_at"))), "work_state": work_state,
            "_fields": {"definition": listed.instance, "operation": group, "id": source_id, "status": status,
                        "state_mapping": state_source},
        }

    def is_closed(self, record: Mapping[str, Any], intake: Mapping[str, Any]) -> bool:
        path = intake["fields"].get("status")
        return is_closed(_scalar(get_path(record, path)) if path else None, intake)

    def in_scope(self, item: WorkItem, listed: Listed) -> bool:
        """The read is the intake's whole scope (the role's grant already narrowed it server-side)."""
        return True

    def query_preview(self, intake: Mapping[str, Any]) -> str:
        return f"{intake['definition']}.{intake['operation']}"

    def summary_extra(self, listed: Listed, intake: Mapping[str, Any]) -> dict[str, Any]:
        detail = dict(listed.detail or {})
        return {"definition": listed.instance, "operation": detail.get("operation"), "role": detail.get("role"),
                "pages": detail.get("pages")}


RECORDS = CustomRestRecords()

__all__ = ["RECORDS", "SYNC_AUDIT_ACTION", "CustomRestRecords", "identifier"]
