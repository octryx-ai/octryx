"""The contract of a Work source: what every intake source provides, so no caller branches on its name."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, User, WorkItem, WorkItemSyncConfig


@dataclass(frozen=True, slots=True)
class Changed:
    closed: dict[str, dict[str, Any]] = field(default_factory=dict)
    minutes: int | None = None
    complete: bool = True


@dataclass(frozen=True, slots=True)
class Listed:
    entries: list[tuple[str, Mapping[str, Any]]]
    complete: bool
    instance: str
    changed: Changed = field(default_factory=Changed)
    detail: Any = None
    counts: dict[str, int] = field(default_factory=dict)


class RecordSource(Protocol):
    source_type: str
    label: str
    sync_audit_action: str

    def intake_of(self, row: WorkItemSyncConfig) -> dict[str, Any]: ...

    async def read(self, db: AsyncSession, row: WorkItemSyncConfig, intake: Mapping[str, Any],
                   *, dry_run: bool, user: User) -> Listed: ...

    def payload(self, row: WorkItemSyncConfig, listed: Listed, group: str, record: Mapping[str, Any],
                intake: Mapping[str, Any]) -> dict[str, Any] | None: ...

    def is_closed(self, record: Mapping[str, Any], intake: Mapping[str, Any]) -> bool: ...

    def in_scope(self, item: WorkItem, listed: Listed) -> bool: ...

    def query_preview(self, intake: Mapping[str, Any]) -> str: ...

    def summary_extra(self, listed: Listed, intake: Mapping[str, Any]) -> dict[str, Any]: ...


class WorkIntakeSource(Protocol):
    source_type: str
    label: str
    #: The named-connection tool an intake of this source reads through (``None``: the source has its own).
    connector: str | None
    #: The filter key whose values bind the intake to a connection's scope (``intake/connections``).
    key_field: str | None
    #: The draft's ``what`` keys (the overview shows them).
    what_keys: tuple[str, ...]
    #: Whether its scheduled run starts the automatic analyses itself (Jira's runner does).
    analyzes_after_sync: bool

    def scope_key(self, item: WorkItem) -> str: ...

    def wants_auto_analysis(self, item: WorkItem, settings: Any, options: Mapping[str, Any]) -> bool: ...

    def draft_what(self, row: WorkItemSyncConfig) -> tuple[dict[str, Any], dict[str, Any]]: ...

    async def save(self, db: AsyncSession, *, user: User, project_id: str, draft: dict[str, Any],
                   how: dict[str, Any], name: str, row: WorkItemSyncConfig | None) -> WorkItemSyncConfig: ...

    async def discover(self, db: AsyncSession, project_id: str, connection_id: str) -> dict[str, Any]: ...

    async def count(self, db: AsyncSession, project_id: str, connection_id: str,
                    what: dict[str, Any]) -> dict[str, Any]: ...

    async def require_connection(self, db: AsyncSession, project_id: str, connection_id: Any) -> None: ...

    async def preview(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> dict[str, Any]: ...

    async def sync(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig, trigger: str) -> dict[str, Any]: ...

    async def reschedule(self, db: AsyncSession, *, user: User, row: WorkItemSyncConfig) -> None: ...

    async def run_scheduled(self, db: AsyncSession, *, task: Task, task_run: Any) -> dict[str, Any]: ...


__all__ = ["Changed", "Listed", "RecordSource", "WorkIntakeSource"]
