"""The report of one Source Sync run.

Counts per fixed outcome (``COUNT_KEYS``), a bounded list of per-item outcomes (a withheld item's
title is never recorded: every Workspace member can read the report), skip reasons, and the run's
freshness facts:

- ``mode``: ``full`` (header listing pass only), ``incremental`` (changed pages first, then the
  header pass) or ``incremental_fallback`` (the change listing failed; the header pass covered it);
- ``withheld`` / ``withheld_reasons``: the connector's *current* withheld items, counted from
  item state among the items the source still lists, not only this run's;
- ``acl_enforced``: whether the Workspace enforces source ACLs (the withheld explanation depends on it);
- ``pass_completed``: this run completed a listing pass (deletions were retired);
- ``scopes`` (a Confluence connector over spaces of several named connections): per space, the
  connection that read it (its name and id, ``default`` for the default connection) and the space's
  listed items and outcomes;
- ``listing`` (a connector reading through a data scope, ``custom_rest``): the role it read as, the pages it read
  and how many records the scope's result filter dropped (never ingested).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import (
    ITEM_STATE_WITHHELD,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
)
from .contract import WITHHELD_REASONS
from .cursor import SyncCursor
from .incremental import MODE_FULL
from .items import ConnectorRef

MAX_RECORDED_OUTCOMES = 200
COUNT_KEYS = ("created", "updated", "unchanged", "retired", "skipped", "failed", "deferred")
UNFINISHED_OUTCOMES = ("failed", "deferred")


@dataclass
class RunReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNT_KEYS, 0))
    outcomes: list[dict[str, object]] = field(default_factory=list)
    listed: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    mode: str = MODE_FULL
    acl_enforced: bool = False
    pass_completed: bool = False
    # The connector's current withheld items by reason, filled in when the run finishes.
    withheld_current: dict[str, int] | None = None
    # Each item's outcome in this run, so a page the change listing already handled is counted
    # once; a repeat of an unfinished one still keeps the header pass from counting as clean.
    handled: dict[str, str] = field(default_factory=dict)
    repeated_unfinished: int = 0
    # The space of an item and the connection of each space, when the connector reports them.
    scope_of: Callable[[str], str | None] | None = field(default=None, repr=False)
    scope_connections: dict[str, tuple[str, str]] = field(default_factory=dict)
    per_scope: dict[str, dict[str, int]] = field(default_factory=dict)
    # A connector's own listing facts (``custom_rest``: the acting role, pages read, records its data scope dropped),
    # read when the report is written, so the facts of the whole run are included.
    listing_facts: dict[str, object] | None = field(default=None, repr=False)

    def attach_scopes(self, connector: object) -> None:
        """Count per space for a connector that reads its spaces with several connections."""
        scope_of, names = getattr(connector, "scope_of", None), getattr(connector, "scope_connections", None)
        if callable(scope_of) and callable(names):
            self.scope_of = scope_of
            self.scope_connections = dict(names())
        facts = getattr(connector, "listing_facts", None)
        if isinstance(facts, dict):
            self.listing_facts = facts

    def _scope_bucket(self, external_id: str | None) -> dict[str, int] | None:
        scope = self.scope_of(external_id) if self.scope_of is not None and external_id is not None else None
        if scope is None:
            return None
        return self.per_scope.setdefault(scope, {"listed": 0, **dict.fromkeys(COUNT_KEYS, 0)})

    def count_listed(self, items: tuple[object, ...]) -> None:
        """Count the items of a listed page not yet handled in this run, also per space."""
        for item in items:
            if self.is_new(item):
                self.listed += 1
                bucket = self._scope_bucket(getattr(item, "external_id", None))
                if bucket is not None:
                    bucket["listed"] += 1

    def is_new(self, item: object) -> bool:
        """Whether ``item`` was not yet handled in this run (it counts as listed)."""
        return getattr(item, "external_id", None) not in self.handled

    def repeats(self, external_id: str) -> bool:
        """True (and nothing is counted again) when this run already handled ``external_id``."""
        earlier = self.handled.get(external_id)
        if earlier is None:
            return False
        if earlier in UNFINISHED_OUTCOMES:
            self.repeated_unfinished += 1
        return True

    @property
    def unfinished(self) -> int:
        """Failed or deferred items so far, including repeats of them."""
        return self.counts["failed"] + self.counts["deferred"] + self.repeated_unfinished

    def record(
        self, external_id: str | None, outcome: str, *, reason: str | None = None, title: str | None = None
    ) -> None:
        self.counts[outcome] += 1
        bucket = self._scope_bucket(external_id)
        if bucket is not None:
            bucket[outcome] += 1
        if external_id is not None:
            self.handled[external_id] = outcome
        if outcome == "skipped" and reason is not None:
            self.skipped_reasons[reason] = self.skipped_reasons.get(reason, 0) + 1
        if len(self.outcomes) < MAX_RECORDED_OUTCOMES:
            # A withheld item's title is never recorded: the report is readable by the Workspace.
            self.outcomes.append({"external_id": external_id, "title": title, "outcome": outcome, "reason": reason})

    def as_dict(self) -> dict[str, object]:
        if self.withheld_current is None:
            withheld_reasons = {r: n for r, n in self.skipped_reasons.items() if r in WITHHELD_REASONS}
        else:
            withheld_reasons = dict(self.withheld_current)
        described: dict[str, object] = {
            **self.counts,
            "listed": self.listed,
            "outcomes_recorded": len(self.outcomes),
            "mode": self.mode,
            # The connector's current total, not only this run's; by reason for the explanation.
            "withheld": sum(withheld_reasons.values()),
            "withheld_reasons": dict(sorted(withheld_reasons.items())),
            "acl_enforced": self.acl_enforced,
            "pass_completed": self.pass_completed,
        }
        if self.skipped_reasons:
            described["skipped_reasons"] = dict(sorted(self.skipped_reasons.items()))
        if self.listing_facts is not None:
            described["listing"] = dict(self.listing_facts)
        if self.scope_connections:
            empty = {"listed": 0, **dict.fromkeys(COUNT_KEYS, 0)}
            described["scopes"] = {
                space: {"connection": name, "connection_id": ref, **self.per_scope.get(space, empty)}
                for space, (name, ref) in self.scope_connections.items()
            }
        return described




async def current_withheld(db: AsyncSession, ref: ConnectorRef) -> dict[str, int]:
    """Withheld items by reason among those the source still lists (seen in the last or open pass)."""
    row = await db.get(KnowledgeSourceConnector, ref.id)
    cursor = SyncCursor.load(row.cursor)
    since_pass = cursor.pass_number - 1 if cursor.pass_open else cursor.pass_number
    rows = await db.execute(
        select(KnowledgeSourceSyncItem.last_outcome, func.count())
        .where(
            KnowledgeSourceSyncItem.connector_id == ref.id,
            KnowledgeSourceSyncItem.project_id == ref.project_id,
            KnowledgeSourceSyncItem.state == ITEM_STATE_WITHHELD,
            KnowledgeSourceSyncItem.last_seen_pass >= since_pass,
        )
        .group_by(KnowledgeSourceSyncItem.last_outcome)
    )
    return {str(reason): int(count) for reason, count in rows.all() if reason in WITHHELD_REASONS}


__all__ = ["COUNT_KEYS", "MAX_RECORDED_OUTCOMES", "RunReport", "current_withheld"]
