"""Did this request already write a domain audit event?"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import event

from ...models import AuditLog

MIDDLEWARE_RESOURCE_TYPE = "api"
_SCOPE: ContextVar[dict[str, int] | None] = ContextVar("audit_request_scope", default=None)


def open_request_scope() -> dict[str, int]:
    holder = {"domain_events": 0}
    _SCOPE.set(holder)
    return holder


def close_request_scope() -> None:
    _SCOPE.set(None)


@event.listens_for(AuditLog, "after_insert")
def _audit_row_inserted(_mapper: Any, _connection: Any, row: AuditLog) -> None:
    holder = _SCOPE.get()
    if holder is not None and row.resource_type != MIDDLEWARE_RESOURCE_TYPE:
        holder["domain_events"] += 1
