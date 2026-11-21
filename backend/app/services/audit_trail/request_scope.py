"""Did this request already write a domain audit event? (O5: one event per change.)

The request middleware opens a scope before the route runs. A mapper listener marks the scope whenever an
``audit_log`` row other than the middleware's own (``resource_type == "api"``) is inserted while the request runs, so
the middleware writes its generic ``METHOD path`` row only for requests without a domain event (no double login or
device events). The scope is a mutable holder in a context variable: the route runs in a copied context, and both
see the same holder.
"""

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
