"""ServiceNow's record-level part of the shared intake pipeline (``intake/pipeline``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkItem, WorkItemSyncConfig
from ...named_connections.contract import DEFAULT_CONNECTION_NAME
from ...servicenow_record_limit import describe
from ..intake.connections import intake_connection_config
from ..intake.pipeline import text
from ..intake.protocol import Listed
from ..jira_values import parse_datetime
from .changed_since import changed_closed_records, window_minutes
from .config import SOURCE_TYPE, is_closed, mapped_state, normalize_intake
from .source import CODE_CONNECTION_UNAVAILABLE, IntakeSourceError, Listing, list_open_records

SYNC_AUDIT_ACTION = "secure_work.servicenow_intake.synced"


def intake_of(row: WorkItemSyncConfig) -> dict[str, Any]:
    stored = {**dict(row.filters_json or {}), **dict(row.field_mapping_json or {}), **dict(row.sync_options_json or {})}
    return {**normalize_intake(stored), "connection_id": row.connection_id or DEFAULT_CONNECTION_NAME}


async def intake_connection(db: AsyncSession, row: WorkItemSyncConfig) -> dict[str, Any]:
    try:
        config = await intake_connection_config(db, row, SOURCE_TYPE)
    except HTTPException as error:  # the connection refuses the intake: its fixed code
        detail = error.detail if isinstance(error.detail, dict) else {}
        raise IntakeSourceError(str(detail.get("code") or CODE_CONNECTION_UNAVAILABLE),
                                "The intake's connection cannot be used") from None
    if config is None:
        raise IntakeSourceError(CODE_CONNECTION_UNAVAILABLE, "The intake's connection is no longer available")
    return config


def _fields(record: Mapping[str, Any], table: str, state_source: str) -> dict[str, Any]:
    fields = {"table": table, "sys_id": record.get("sys_id"), "state": record.get("state"),
              "assignment_group": record.get("assignment_group"), "opened_at": record.get("opened_at"),
              "state_mapping": state_source}
    service = record.get("service") or record.get("business_service")
    if service:
        fields["service"] = service
    for key in ("assignment_group_sys_id", "service_sys_id"):
        if record.get(key):
            fields[key] = record[key]
    return fields


def _caller(record: Mapping[str, Any]) -> str | None:
    # A person is matched by identifier only: a display name stays unmatched.
    for key in ("caller_id.email", "caller_id.user_name"):
        if text(record.get(key), 220):
            return text(record.get(key), 220)
    value = record.get("caller_id")
    if isinstance(value, Mapping):
        value = value.get("value") or value.get("display_value")
    return text(value, 220)


class ServiceNowRecords:
    source_type = SOURCE_TYPE
    label = "ServiceNow"
    sync_audit_action = SYNC_AUDIT_ACTION

    def intake_of(self, row: WorkItemSyncConfig) -> dict[str, Any]:
        return intake_of(row)

    async def read(self, db: AsyncSession, row: WorkItemSyncConfig, intake: Mapping[str, Any], *, dry_run: bool,
                   user: User) -> Listed:
        config = await intake_connection(db, row)
        listing = await list_open_records(config, intake)
        found = await changed_closed_records(config, intake, window_minutes(row))
        entries = [(table, record) for table, records in listing.records.items() for record in records]
        return Listed(entries=entries, complete=listing.complete, instance=listing.instance, detail=listing,
                      changed=found)

    def payload(self, row: WorkItemSyncConfig, listed: Listed, group: str, record: Mapping[str, Any],
                intake: Mapping[str, Any]) -> dict[str, Any] | None:
        sys_id, number = text(record.get("sys_id"), 220), text(record.get("number"), 220)
        if sys_id is None or number is None:
            return None
        work_state, state_source = mapped_state(record.get("state"), intake)
        return {
            "project_id": row.project_id, "sync_config_id": row.id, "source_type": SOURCE_TYPE,
            "source_instance": listed.instance, "source_id": sys_id, "source_project_key": group,
            "source_key": number, "source_url": record.get("url"), "issue_type": group,
            "title": text(record.get("short_description"), 500) or number,
            "description": text(record.get("description"), 20000), "source_status": text(record.get("state"), 120),
            "priority": text(record.get("priority"), 120), "assignee": text(record.get("assigned_to"), 220),
            # The caller is the reporter: the first link of a run's responsible chain.
            "reporter": _caller(record),
            "source_created_at": parse_datetime(record.get("opened_at")), "work_state": work_state,
            "_fields": _fields(record, group, state_source),
        }

    def is_closed(self, record: Mapping[str, Any], intake: Mapping[str, Any]) -> bool:
        return is_closed(record.get("state"), intake)

    def in_scope(self, item: WorkItem, listed: Listed) -> bool:
        listing: Listing = listed.detail
        if listing.limit is None:
            return True
        stored = (item.source_fields_json or {}).get(SOURCE_TYPE) if isinstance(item.source_fields_json, dict) \
            else None
        stored = stored if isinstance(stored, dict) else {}
        return listing.limit.matches({
            "assignment_groups": (stored.get("assignment_group_sys_id"), stored.get("assignment_group")),
            "services": (stored.get("service_sys_id"), stored.get("service")),
        })

    def query_preview(self, intake: Mapping[str, Any]) -> str:
        return ",".join(intake["tables"])

    def summary_extra(self, listed: Listed, intake: Mapping[str, Any]) -> dict[str, Any]:
        return {"tables": intake["tables"], **describe(listed.detail.limit)}


RECORDS = ServiceNowRecords()

__all__ = ["RECORDS", "SYNC_AUDIT_ACTION", "ServiceNowRecords", "intake_connection", "intake_of"]
