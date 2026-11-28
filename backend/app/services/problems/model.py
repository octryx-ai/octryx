"""The shape of one problem and the context every collector reads with (problems aggregator)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, false, true

from ...time_utils import ensure_utc

KIND_CONNECTION = "connection"
KIND_SYNC = "sync"
KIND_INTAKE = "intake"
KIND_RUN = "run"
KIND_RULE_DENIAL = "rule_denial"
KIND_TOKEN = "token"
KIND_DEVICE = "device"
KIND_BUDGET = "budget"
KINDS = (KIND_CONNECTION, KIND_SYNC, KIND_INTAKE, KIND_RUN, KIND_RULE_DENIAL, KIND_TOKEN, KIND_DEVICE, KIND_BUDGET)

SEVERITY_PROBLEM = "problem"
SEVERITY_ATTENTION = "attention"
SEVERITIES = (SEVERITY_PROBLEM, SEVERITY_ATTENTION)

WINDOW = timedelta(days=7)
ROW_LIMIT = 50
# Two parts of at most 90 characters keep a key within 200 (``audit_log.resource_id``).
_MAX_KEY_PART = 90


@dataclass(frozen=True)
class CollectContext:
    now: datetime
    workspace_ids: frozenset[str] | None = None
    limit: int = ROW_LIMIT
    viewer_id: str | None = None

    @property
    def window_start(self) -> datetime:
        return self.now - WINDOW

    def scope(self, column: Any) -> ColumnElement[bool]:
        from ..project.private_workspace import outside_foreign_private  # noqa: PLC0415

        if self.workspace_ids is None:
            condition = true()
        else:
            condition = column.in_(sorted(self.workspace_ids)) if self.workspace_ids else false()
        return condition if self.viewer_id is None else condition & outside_foreign_private(column, self.viewer_id)


@dataclass
class Problem:
    kind: str
    severity: str
    object_type: str
    object_id: str
    object_name: str
    reason_code: str
    title: str
    since: datetime | None
    last_seen: datetime | None
    fix: dict[str, str]
    count: int = 1
    workspace_id: str | None = None
    key_object_id: str | None = None
    workspace_name: str | None = field(default=None, compare=False)
    # The connection (``connector_named_connections`` id) the problem is about, for its page's count.
    connection_id: str | None = field(default=None, compare=False)

    @property
    def key(self) -> str:
        return problem_key(self.kind, self.key_object_id or self.object_id, self.reason_code)

    def to_dict(self) -> dict[str, Any]:
        workspace = ({"id": self.workspace_id, "name": self.workspace_name or self.workspace_id}
                     if self.workspace_id else None)
        return {
            "key": self.key, "kind": self.kind, "severity": self.severity, "title": self.title,
            "since": iso(self.since), "last_seen": iso(self.last_seen), "count": int(self.count),
            "workspace": workspace,
            "object": {"type": self.object_type, "id": self.object_id, "name": self.object_name},
            "fix": dict(self.fix),
        }


def iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _key_part(value: str) -> str:
    text = str(value or "").strip() or "-"
    if len(text) <= _MAX_KEY_PART:
        return text
    return "h_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def problem_key(kind: str, object_id: str, reason_code: str) -> str:
    return f"{kind}:{_key_part(object_id)}:{_key_part(reason_code)}"


def scoped_object_id(object_id: str, workspace_id: str | None) -> str:
    return f"{object_id}@{workspace_id}" if workspace_id else object_id


def workspace_of(value: str | None) -> str | None:
    return str(value) if value else None


__all__ = [
    "KINDS",
    "ROW_LIMIT",
    "SEVERITIES",
    "SEVERITY_ATTENTION",
    "SEVERITY_PROBLEM",
    "WINDOW",
    "CollectContext",
    "Problem",
    "iso",
    "problem_key",
    "scoped_object_id",
    "workspace_of",
]
