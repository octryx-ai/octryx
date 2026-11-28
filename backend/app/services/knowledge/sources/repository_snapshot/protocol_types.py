"""The bodies of ``POST /api/v1/agent-gateway/sessions/repository[/manifest|/files|/complete]`` and the state they
leave on the session and the source. The launcher (``clients/octryx-claude``, ``snapshot.py``) builds against them."""

from typing import Literal, NotRequired, TypedDict

from ..sync.stored_types import StoredSyncCursor

LinkMode = Literal["host", "platform"]
SnapshotPermissionState = Literal["allowed", "denied"]
FileOutcome = Literal["ingested", "skipped", "failed"]
CompleteState = Literal["indexed", "incomplete"]


class BindRequest(TypedDict):
    remote_url: str  # credential-free: the launcher drops userinfo, query and fragment before sending
    head_commit: str
    # The server reads an absent flag as false and an absent branch or root as null; the launcher sends all four.
    head_dirty: NotRequired[bool]  # a status git cannot read counts as dirty
    head_pushed: NotRequired[bool]  # a remote-tracking branch contains HEAD
    branch: NotRequired[str | None]
    root: NotRequired[str | None]  # the checkout's absolute path: the only place a confirmed change workflow may edit


class BoundRepository(TypedDict):
    connector_key: str
    repository: str
    workspace_id: str
    head_commit: str
    head_dirty: bool
    links: LinkMode
    label: str | None


class SnapshotPermission(TypedDict):
    state: SnapshotPermissionState
    reason: str | None


class BindResponse(TypedDict):
    state: Literal["bound"]
    binding: BoundRepository
    snapshot: SnapshotPermission


class ManifestEntry(TypedDict):
    path: str
    blob_sha: str
    size: int


class ManifestRequest(TypedDict):
    head_commit: str
    files: list[ManifestEntry]
    truncated: NotRequired[bool]  # absent reads as false; true: the launcher listed only its first MAX_TREE_FILES


class SkippedPath(TypedDict):
    path: str
    reason: str


class ManifestResponse(TypedDict):
    state: Literal["ok"]
    wanted: list[str]
    unchanged: int
    skipped: list[SkippedPath]
    knowledge: dict[str, str | None]


class FileUpload(TypedDict):
    path: str
    blob_sha: str
    content_base64: str


class FilesRequest(TypedDict):
    head_commit: str
    files: list[FileUpload]


class FileResult(TypedDict):
    path: str
    outcome: FileOutcome
    reason: str | None


class FilesResponse(TypedDict):
    state: Literal["ok"]
    results: list[FileResult]


class CompleteRequest(TypedDict):
    head_commit: str


class CompleteResponse(TypedDict):
    state: CompleteState
    files_indexed: int
    files_new: int
    files_removed: int
    missing: int  # wanted files never uploaded; the pass stays open


class SessionBinding(TypedDict):
    connector_key: str
    connector_id: str | None  # None: no source for the remote, and local snapshots are not allowed
    repository: str
    remote: str
    head_commit: str
    head_dirty: bool
    head_pushed: bool
    branch: str | None
    root: str | None
    links: LinkMode
    bound_at: str


class SnapshotPassState(TypedDict):
    commit: str
    wanted: dict[str, str]  # path -> blob sha still to upload
    ingested: int
    listed: int
    truncated: bool


class SnapshotCursor(StoredSyncCursor):
    snapshot: NotRequired[SnapshotPassState]  # only while a pass is open


__all__ = [
    "BindRequest",
    "BindResponse",
    "BoundRepository",
    "CompleteRequest",
    "CompleteResponse",
    "CompleteState",
    "FileOutcome",
    "FileResult",
    "FileUpload",
    "FilesRequest",
    "FilesResponse",
    "LinkMode",
    "ManifestEntry",
    "ManifestRequest",
    "ManifestResponse",
    "SessionBinding",
    "SkippedPath",
    "SnapshotCursor",
    "SnapshotPassState",
    "SnapshotPermission",
    "SnapshotPermissionState",
]
