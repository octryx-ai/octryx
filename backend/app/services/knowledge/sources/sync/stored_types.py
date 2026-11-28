"""The JSON a Source Sync connector stores: its cursor, its ``custom_rest`` and Jira release configuration, and the
report and outcomes of a run."""

from typing import Any, Literal, NotRequired, Required, TypedDict

SyncOutcome = Literal["created", "updated", "unchanged", "retired", "skipped", "failed", "deferred"]
SyncMode = Literal["full", "incremental", "incremental_fallback"]
RestMediaType = Literal["application/json", "text/markdown", "text/plain", "text/html", "application/pdf"]
RestVisibility = Literal["restricted", "workspace"]
ReleaseSyncStateName = Literal["off", "active", "needs_configuration"]


class StoredSyncCursor(TypedDict):
    pass_number: int
    token: str | None  # the connector's opaque page token inside the open pass; None at a pass start
    pass_started_at: str | None  # set only while a pass is open
    last_completed_at: str | None
    completed_passes: int
    # The next incremental listing asks for changes since this instant: the start of the last clean pass or
    # incremental listing, so nothing changed during a pass is missed.
    changes_since: str | None
    incremental_started_at: str | None
    incremental_token: str | None
    pass_failures: int
    last_pass_closed_at: str | None
    last_pass_failures: int | None
    # A scheduled run never resumes a pass a manual run began: the items before its token would miss that
    # interval's ACL check.
    pass_scheduled: bool


class RestRecordMapping(TypedDict, total=False):
    id: Required[str]
    title: Required[str]
    url: str
    updated_at: str
    version: str
    content: str


class RestSourceScope(TypedDict):
    definition: str
    operation: str
    role: str | None  # the Octryx role whose grant and data scope the sync runs in
    arguments: dict[str, Any]
    detail_operation: str | None
    detail_param: str | None
    updated_since_param: str | None
    media_type: RestMediaType
    visibility: RestVisibility
    mapping: RestRecordMapping


class ReleaseSectionConfig(TypedDict):
    title: str
    issue_types: list[str]
    labels: list[str]


class StoredReleaseConfig(TypedDict):
    products: dict[str, str]  # Jira project key -> product key; a project without an entry has no release sync
    version_name_prefixes: list[str]
    sections: list[ReleaseSectionConfig]
    blocker_priorities: list[str]


class RecordedOutcome(TypedDict):
    external_id: str | None
    title: str | None  # never a withheld item's: every Workspace member can read the run
    outcome: SyncOutcome
    reason: str | None


class RestListingFacts(TypedDict):
    role: str
    pages: int
    dropped_out_of_scope: int


class ScopeReport(TypedDict):
    connection: str
    connection_id: str
    listed: int
    created: int
    updated: int
    unchanged: int
    retired: int
    skipped: int
    failed: int
    deferred: int


class RepositoryRunFacts(TypedDict):
    ref: str | None
    commit: str | None
    empty: NotRequired[bool]  # the repository has no commit yet: the run completes with no item


class ReleaseSyncState(TypedDict):
    state: ReleaseSyncStateName
    reason: NotRequired[str]
    products: NotRequired[dict[str, str]]


class StoredRunReport(TypedDict):
    created: int
    updated: int
    unchanged: int
    retired: int
    skipped: int
    failed: int
    deferred: int
    listed: int
    outcomes_recorded: int
    mode: SyncMode
    withheld: int  # the connector's current withheld items, not only this run's
    withheld_reasons: dict[str, int]
    acl_enforced: bool
    pass_completed: bool
    skipped_reasons: NotRequired[dict[str, int]]
    listing: NotRequired[RestListingFacts]
    scopes: NotRequired[dict[str, ScopeReport]]  # per space, when one connector reads spaces of several connections
    completed_with_failures: NotRequired[bool]  # set when the run finishes
    repository: NotRequired[RepositoryRunFacts]  # git_repository runs
    release_sync: NotRequired[ReleaseSyncState]  # Jira runs whose release sync is not off


class EmptyRunReport(TypedDict):
    pass


# A run refused before it starts, or one still running, stores an empty report.
PersistedRunReport = StoredRunReport | EmptyRunReport


__all__ = [
    "EmptyRunReport",
    "PersistedRunReport",
    "RecordedOutcome",
    "ReleaseSectionConfig",
    "ReleaseSyncState",
    "ReleaseSyncStateName",
    "RepositoryRunFacts",
    "RestListingFacts",
    "RestMediaType",
    "RestRecordMapping",
    "RestSourceScope",
    "RestVisibility",
    "ScopeReport",
    "StoredReleaseConfig",
    "StoredRunReport",
    "StoredSyncCursor",
    "SyncMode",
    "SyncOutcome",
]
