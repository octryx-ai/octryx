"""The durable cursor of one connector: which listing pass, and where inside it the next run resumes.

Stored as JSON on ``KnowledgeSourceConnector.cursor``. ``pass_number`` counts listing passes;
``token`` is the connector's opaque page token inside the open pass (``None`` at a pass start);
``pass_started_at`` is set while a pass is open and cleared when it completes, at which point
``last_completed_at`` and ``completed_passes`` advance. A malformed stored value is a contract
violation, never silently reset: resetting would restart a pass and could hide a defect.

Incremental change detection keeps three more optional fields in the same JSON:
``changes_since`` is the instant from which the next incremental listing asks for
changed items (the start of the last completed full pass or incremental listing);
``incremental_started_at`` and ``incremental_token`` describe an open incremental listing. A
completed full pass sets ``changes_since`` to its own start, so nothing changed during the pass is
missed. A cursor without them (no completed pass yet) starts with a full pass.

A pass counts as a *clean* reconciliation only when none of its items failed or had their fetch
deferred: only then do ``last_completed_at``, ``completed_passes`` and ``changes_since``
advance, so a failed item is still inside the next change window. Every closed pass records
``last_pass_closed_at`` and ``last_pass_failures``; ``pass_failures`` counts inside the open pass.

``pass_scheduled`` says whether a scheduled run began the open pass. A scheduled run never resumes a
pass a manual run began: the items before its cursor would miss that interval's
ACL check, so it begins a fresh header pass instead.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ...ledger.errors import EvidenceLedgerContractError

# A Confluence Cloud page token carries the source's own ``_links.next`` (an opaque cursor).
MAX_TOKEN_CHARS = 1000
_OPTIONAL_TEXT = (
    "pass_started_at",
    "last_completed_at",
    "changes_since",
    "incremental_started_at",
    "last_pass_closed_at",
)


def _valid_token(token: object) -> bool:
    return token is None or (type(token) is str and len(token) <= MAX_TOKEN_CHARS)


@dataclass(frozen=True, slots=True)
class SyncCursor:
    pass_number: int = 0
    token: str | None = None
    pass_started_at: str | None = None
    last_completed_at: str | None = None
    completed_passes: int = 0
    changes_since: str | None = None
    incremental_started_at: str | None = None
    incremental_token: str | None = None
    pass_failures: int = 0
    last_pass_closed_at: str | None = None
    last_pass_failures: int | None = None
    pass_scheduled: bool = False

    @classmethod
    def load(cls, raw: object) -> SyncCursor:
        if raw in (None, {}):
            return cls()
        if not isinstance(raw, dict):
            raise EvidenceLedgerContractError()
        cursor = cls(
            pass_number=raw.get("pass_number", 0),
            token=raw.get("token"),
            pass_started_at=raw.get("pass_started_at"),
            last_completed_at=raw.get("last_completed_at"),
            completed_passes=raw.get("completed_passes", 0),
            changes_since=raw.get("changes_since"),
            incremental_started_at=raw.get("incremental_started_at"),
            incremental_token=raw.get("incremental_token"),
            pass_failures=raw.get("pass_failures", 0),
            last_pass_closed_at=raw.get("last_pass_closed_at"),
            last_pass_failures=raw.get("last_pass_failures"),
            pass_scheduled=raw.get("pass_scheduled", False),
        )
        if type(cursor.pass_scheduled) is not bool:
            raise EvidenceLedgerContractError()
        if type(cursor.pass_number) is not int or type(cursor.completed_passes) is not int:
            raise EvidenceLedgerContractError()
        if type(cursor.pass_failures) is not int or (
            cursor.last_pass_failures is not None and type(cursor.last_pass_failures) is not int
        ):
            raise EvidenceLedgerContractError()
        if not _valid_token(cursor.token) or not _valid_token(cursor.incremental_token):
            raise EvidenceLedgerContractError()
        if any(getattr(cursor, name) is not None and type(getattr(cursor, name)) is not str for name in _OPTIONAL_TEXT):
            raise EvidenceLedgerContractError()
        return cursor

    @property
    def pass_open(self) -> bool:
        return self.pass_started_at is not None

    @property
    def incremental_open(self) -> bool:
        return self.incremental_started_at is not None

    def begin_pass(self, now: datetime, *, scheduled: bool = False) -> SyncCursor:
        return replace(
            self,
            pass_scheduled=scheduled,
            pass_number=self.pass_number + 1,
            token=None,
            pass_started_at=now.isoformat(),
            incremental_started_at=None,
            incremental_token=None,
            pass_failures=0,
        )

    def at(self, token: str | None) -> SyncCursor:
        if not _valid_token(token):
            raise EvidenceLedgerContractError()
        return replace(self, token=token)

    def with_failures(self, count: int) -> SyncCursor:
        return replace(self, pass_failures=self.pass_failures + max(0, count))

    def complete_pass(self, now: datetime) -> SyncCursor:
        closed = replace(
            self,
            token=None,
            pass_started_at=None,
            pass_failures=0,
            pass_scheduled=False,
            last_pass_closed_at=now.isoformat(),
            last_pass_failures=self.pass_failures,
        )
        if self.pass_failures:
            # Not a clean reconciliation: freshness markers stay where they were.
            return closed
        return replace(
            closed,
            last_completed_at=now.isoformat(),
            completed_passes=self.completed_passes + 1,
            # Everything changed since this pass began is still asked for by the next incremental run.
            changes_since=self.pass_started_at,
        )

    def begin_incremental(self, now: datetime) -> SyncCursor:
        return replace(self, incremental_started_at=now.isoformat(), incremental_token=None)

    def at_incremental(self, token: str | None) -> SyncCursor:
        if not _valid_token(token):
            raise EvidenceLedgerContractError()
        return replace(self, incremental_token=token)

    def complete_incremental(self) -> SyncCursor:
        return replace(
            self, changes_since=self.incremental_started_at, incremental_started_at=None, incremental_token=None
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "pass_number": self.pass_number,
            "token": self.token,
            "pass_started_at": self.pass_started_at,
            "last_completed_at": self.last_completed_at,
            "completed_passes": self.completed_passes,
            "changes_since": self.changes_since,
            "incremental_started_at": self.incremental_started_at,
            "incremental_token": self.incremental_token,
            "pass_failures": self.pass_failures,
            "last_pass_closed_at": self.last_pass_closed_at,
            "last_pass_failures": self.last_pass_failures,
            "pass_scheduled": self.pass_scheduled,
        }


__all__ = ["MAX_TOKEN_CHARS", "SyncCursor"]
