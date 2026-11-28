"""``PUT /api/v1/admin/connections/{id}`` ``uses``: the connection's own level and its linked uses."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, User, WorkItemSyncConfig
from ...models.project.knowledge_source_sync import (
    CONNECTOR_STATE_ACTIVE,
    CONNECTOR_STATE_PAUSED,
    KnowledgeSourceConnector,
)
from ...time_utils import utc_now
from ..named_connections.descriptors import descriptor_of
from ..named_connections.grants import has_credentials
from . import schedules
from .auth_fields import CODE_LEVEL_REQUIRES_CREDENTIALS
from .catalog import KNOWLEDGE_SCOPE_FIELDS, SCOPE_KEYS, TICKET_SCOPE_FIELDS, ticket_state_keys, uses_of
from .contract import (
    CODE_SCOPE_OUTSIDE,
    CODE_STATUS_UNKNOWN,
    CODE_USE_NOT_LINKED,
    CODE_USE_SPANS_WORKSPACES,
    CODE_WRITE_BACK_ON_WORKFLOW,
    LEVELS,
    USE_AGENT_TOOLS,
    USE_KNOWLEDGE,
    USE_TICKETS,
    invalid,
    refusal,
)
from .uses_read import intake_rows, knowledge_rows

KNOWLEDGE_KEYS = frozenset({"enabled", "scope", "schedule", "schedule_cron"})
TICKET_KEYS = frozenset({"enabled", "filter", "scope", "schedule", "schedule_cron", "status_map", "write_back"})


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise invalid(field, f"{field} must be true or false.")
    return value


def parse_scope(row: ConnectorNamedConnection, raw: Any, field: str) -> list[str]:
    tool = str(row.tool_name)
    key = SCOPE_KEYS.get(tool)
    if key is None or not isinstance(raw, dict) or set(raw) != {key} or not isinstance(raw[key], list):
        raise invalid(field, f"{field} must be {{{key!r}: [...]}}." if key else f"{field}: this type has no scope.")
    binding = descriptor_of(tool).binding
    items: list[str] = []
    for item in raw[key]:
        if not binding.valid(item):
            raise invalid(f"{field}.{key}", f"{field}.{key}: a key is not a valid {binding.label}.")
        if (canonical := binding.canonical(item)) not in items:
            items.append(canonical)
    bound = set(row.bound_scopes or ())
    if bound and not set(items) <= bound:
        raise invalid(f"{field}.{key}", f"{field}.{key} must stay within the connection's scope.", CODE_SCOPE_OUTSIDE)
    return items


def parse_status_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        raise invalid("uses.tickets.status_map", "uses.tickets.status_map must be a list of {source, ours}.")
    known, mapping = ticket_state_keys(), {}
    for index, entry in enumerate(raw):
        field = f"uses.tickets.status_map[{index}]"
        if not isinstance(entry, dict) or not str(entry.get("source") or "").strip():
            raise invalid(field, f"{field} needs a source status and one of our states.")
        if entry.get("ours") not in known:
            raise invalid(f"{field}.ours", f"{field}.ours must be one of the work item states.", CODE_STATUS_UNKNOWN)
        mapping[str(entry["source"]).strip()] = str(entry["ours"])
    return mapping


def _single(rows: list, use: str) -> Any:
    if not rows:
        raise refusal(409, CODE_USE_NOT_LINKED, f"No {use} use is linked to this connection yet.", f"uses.{use}")
    if len(rows) > 1:
        raise refusal(409, CODE_USE_SPANS_WORKSPACES, f"The {use} use spans several Workspaces; change it in each "
                      "Workspace.", f"uses.{use}")
    return rows[0]


def parse_uses(row: ConnectorNamedConnection, raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise invalid("uses", "uses must be an object.")
    allowed = uses_of(str(row.tool_name))
    parsed: dict[str, dict[str, Any]] = {}
    for use, values in raw.items():
        if use not in allowed or not isinstance(values, dict):
            raise invalid(f"uses.{use}", f"uses.{use} is not a use of this connection type.")
        if use == USE_AGENT_TOOLS:
            if set(values) - {"level"} or values.get("level") not in LEVELS:
                raise invalid("uses.agent_tools.level", "uses.agent_tools.level must be off, read or write.")
            parsed[use] = {"level": values["level"]}
            continue
        keys = KNOWLEDGE_KEYS if use == USE_KNOWLEDGE else TICKET_KEYS if use == USE_TICKETS else frozenset()
        if unknown := sorted(set(values) - keys):
            raise invalid(f"uses.{use}.{unknown[0]}", f"uses.{use}.{unknown[0]} cannot be changed here.")
        if use == USE_TICKETS and "write_back" in values:
            raise invalid("uses.tickets.write_back", "Write-back is set on the Workspace's work item workflow.",
                          CODE_WRITE_BACK_ON_WORKFLOW)
        change: dict[str, Any] = {}
        if "enabled" in values:
            change["enabled"] = _bool(values["enabled"], f"uses.{use}.enabled")
        if "scope" in values:
            change["scope"] = parse_scope(row, values["scope"], f"uses.{use}.scope")
        if "schedule" in values:
            change["schedule"] = schedules.normalize(use, values)
            if use == USE_KNOWLEDGE:
                change["interval"] = schedules.knowledge_interval(change["schedule"])
        if "status_map" in values:
            change["status_map"] = parse_status_map(values["status_map"])
        if "filter" in values:
            if values["filter"] is not None and not isinstance(values["filter"], str):
                raise invalid("uses.tickets.filter", "uses.tickets.filter must be text.")
            change["filter"] = str(values["filter"] or "").strip()
        parsed[use] = change
    return parsed


def _apply_knowledge(row: ConnectorNamedConnection, source: KnowledgeSourceConnector, change: dict, actor_id: str):
    from ..knowledge.sources.sync.cursor import SyncCursor

    if "enabled" in change:
        source.state = CONNECTOR_STATE_ACTIVE if change["enabled"] else CONNECTOR_STATE_PAUSED
    if "scope" in change:
        field = KNOWLEDGE_SCOPE_FIELDS[str(row.tool_name)]
        scope = dict(source.scope or {})
        if list(scope.get(field) or []) != change["scope"]:
            # As a configuration change in the Knowledge service: the next run starts a new listing pass.
            cursor = SyncCursor.load(source.cursor)
            source.cursor = SyncCursor(pass_number=cursor.pass_number, completed_passes=cursor.completed_passes,
                                       last_completed_at=cursor.last_completed_at).as_dict()
            source.scope = {**scope, field: change["scope"]}
    if "interval" in change:
        enabled, minutes = change["interval"]
        if not enabled:
            source.schedule_enabled, source.schedule_owner_id, source.next_scheduled_at = False, None, None
        else:  # the Knowledge service's rule: due now when newly on, a shorter interval takes effect now
            earliest = utc_now() + timedelta(minutes=minutes)
            due = source.next_scheduled_at if source.schedule_enabled and source.next_scheduled_at else utc_now()
            source.next_scheduled_at = min(due, earliest)
            source.schedule_enabled, source.schedule_owner_id = True, actor_id
            source.schedule_interval_minutes = minutes


async def _apply_tickets(db: AsyncSession, user: User, row: ConnectorNamedConnection, intake: WorkItemSyncConfig,
                         change: dict) -> None:
    from ..secure_work.intake.setup import draft_of, save_intake, set_intake_active

    edits = {key: value for key, value in change.items() if key != "enabled"}
    if edits:
        draft = draft_of(intake)
        what = draft["what"]
        if "filter" in edits:
            what["jql" if "jql" in what else "sysparm_query"] = edits["filter"]
        if "scope" in edits:
            what[TICKET_SCOPE_FIELDS[str(row.tool_name)]] = edits["scope"]
        if "schedule" in edits:
            draft["schedule"] = schedules.intake_schedule(edits["schedule"])
        if "status_map" in edits:
            draft["how"]["status_mapping"] = edits["status_map"]
        await save_intake(db, user=user, project_id=intake.project_id, draft=draft, row=intake)
    if "enabled" in change:
        await set_intake_active(db, user=user, row=intake, active=change["enabled"])


async def apply_uses(db: AsyncSession, user: User, row: ConnectorNamedConnection,
                     parsed: dict[str, dict[str, Any]]) -> list[str]:
    targets: dict[str, Any] = {}
    if parsed.get(USE_KNOWLEDGE):
        targets[USE_KNOWLEDGE] = _single((await knowledge_rows(db, [row.id]))[row.id], USE_KNOWLEDGE)
    if parsed.get(USE_TICKETS):
        targets[USE_TICKETS] = _single((await intake_rows(db, [row.id]))[row.id], USE_TICKETS)
    if USE_AGENT_TOOLS in parsed:
        level = parsed[USE_AGENT_TOOLS]["level"]
        if level == "write" and not has_credentials(str(row.tool_name), row.config):
            raise invalid("uses.agent_tools.level", "Agent tools may only read with a connection without sign-in.",
                          CODE_LEVEL_REQUIRES_CREDENTIALS)
        row.agent_tools_level = level
    if USE_KNOWLEDGE in targets:
        _apply_knowledge(row, targets[USE_KNOWLEDGE], parsed[USE_KNOWLEDGE], user.id)
    if USE_TICKETS in targets:
        await _apply_tickets(db, user, row, targets[USE_TICKETS], parsed[USE_TICKETS])
    await db.flush()
    return sorted(use for use, change in parsed.items() if change)


__all__ = ["apply_uses", "parse_scope", "parse_status_map", "parse_uses"]
