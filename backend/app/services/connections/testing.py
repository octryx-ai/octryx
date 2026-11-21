"""``POST /api/v1/admin/connections/{id}/test``: ``{state, state_reason, tested_at, checks}``.

The access check is the named connection's test (``connector_test_service.run_connector_connection_test`` on the
connection's own resolved unit, its allowlist narrowed to its bound keys, the descriptor's runtime guard first so a
test never falls back to a host or platform credential). ``checks[0]`` is always ``use: "access"``; each active
linked use follows (its scope within the connection's keys). The outcome is kept: ``state`` (``ok`` | ``failing``),
``state_reason`` (one sentence when failing), ``last_tested_at`` and ``last_test`` (what the named-connection view
shows). A secret is never part of a result, a log line or the audit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection
from ...models.project.knowledge_source_sync import CONNECTOR_STATE_ACTIVE
from ...time_utils import utc_now
from ..admin.project.named_connection_view import last_test_record
from ..named_connections.descriptor import UnitIncompleteError
from ..named_connections.descriptors import descriptor_of
from ..named_connections.store import resolved_config, to_value
from .catalog import KNOWLEDGE_SCOPE_FIELDS, TICKET_SCOPE_FIELDS
from .contract import CODE_TEST_UNAVAILABLE, STATE_FAILING, STATE_OK, USE_ACCESS, USE_KNOWLEDGE, USE_TICKETS, refusal
from .uses_read import intake_rows, iso, knowledge_rows
from .writes import audit

AUDIT_TESTED = "admin.connection.tested"
REASON_CHARS = 300
RunTest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _sentence(text: Any, fallback: str) -> str:
    return (" ".join(str(text or "").split()) or fallback)[:REASON_CHARS]


def _scope_check(use: str, name: str, keys: list[str], bound: set[str]) -> dict[str, Any]:
    outside = sorted({key.upper() for key in keys} - bound) if bound else []
    if outside:
        return {"use": use, "ok": False, "message": f"{name}: {', '.join(outside)} outside the connection's scope."}
    return {"use": use, "ok": True, "message": f"{name}: scope within the connection."}


async def _use_checks(db: AsyncSession, row: ConnectorNamedConnection) -> list[dict[str, Any]]:
    tool, bound = str(row.tool_name), {str(key).upper() for key in row.bound_scopes or ()}
    checks = []
    for source in (await knowledge_rows(db, [row.id]))[row.id]:
        if source.state == CONNECTOR_STATE_ACTIVE:
            keys = [str(item) for item in (source.scope or {}).get(KNOWLEDGE_SCOPE_FIELDS.get(tool, ""), ()) or ()]
            checks.append(_scope_check(USE_KNOWLEDGE, source.connector_key, keys, bound))
    for intake in (await intake_rows(db, [row.id]))[row.id]:
        if intake.is_active:
            keys = [str(item) for item in (intake.filters_json or {}).get(TICKET_SCOPE_FIELDS.get(tool, ""), ()) or ()]
            checks.append(_scope_check(USE_TICKETS, intake.name, keys, bound))
    return checks


async def test_connection(db: AsyncSession, row: ConnectorNamedConnection, *, actor_id: str,
                          run_test: RunTest) -> dict[str, Any]:
    descriptor = descriptor_of(row.tool_name)
    if descriptor is None or not descriptor.testable:
        raise refusal(409, CODE_TEST_UNAVAILABLE, "This connection type has no connection test.")
    config = await resolved_config(db, to_value(row))
    access: dict[str, Any]
    try:
        if descriptor.runtime_guard is not None:
            descriptor.runtime_guard(config)
    except UnitIncompleteError as incomplete:
        access = {"ok": False, "summary": str(incomplete)}
    else:
        if descriptor.allowlist is not None and row.bound_scopes:
            config[descriptor.allowlist.field] = [descriptor.allowlist.entry(key) for key in sorted(row.bound_scopes)]
        access = await run_test(str(row.tool_name), config)
    ok = bool(access.get("ok"))
    checks = [{"use": USE_ACCESS, "ok": ok,
               "message": _sentence(access.get("summary"), "Signed in." if ok else "Sign-in failed.")}]
    checks += await _use_checks(db, row)
    now = utc_now()
    row.state = STATE_OK if all(check["ok"] for check in checks) else STATE_FAILING
    failed = next((check for check in checks if not check["ok"]), None)
    row.state_reason = failed["message"] if failed else None
    row.last_tested_at, row.last_test = now, last_test_record(access, now)
    audit(db, actor_id, AUDIT_TESTED, row, details={"ok": row.state == STATE_OK,
                                                     "checks": [check["use"] for check in checks]})
    await db.flush()
    return {"state": row.state, "state_reason": row.state_reason, "tested_at": iso(now), "checks": checks}


__all__ = ["AUDIT_TESTED", "test_connection"]
