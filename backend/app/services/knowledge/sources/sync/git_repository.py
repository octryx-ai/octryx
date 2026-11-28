"""The ``git_repository`` Source Sync connector in its ``remote_git`` fetch mode. A pass resolves its ref once, so it
never mixes two commits."""

from __future__ import annotations

import asyncio
import hashlib
import re

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY
from ...code.facets import CodeFileFacet
from ..repository_snapshot.labels import file_title
from .contract import (
    REASON_REPOSITORY_EMPTY,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    AclExpansion,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .git_clone import GitCloneReader, RepositoryEmptyError
from .git_config import GitScope
from .git_hosts import GITHUB, SHA, BitbucketDataCenterHost
from .git_http import GitHostReader, HostStatusError
from .git_paths import language_of
from .git_snapshot import SnapshotEntry, read_snapshot

MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_SKIPPED_PER_PAGE = 500
MAX_REPORTED_PATH_CHARS = 80
MAX_TREE_JSON_BYTES = 64 * 1024  # an empty tree answers a few hundred bytes; a bigger one is not empty
_GITHUB_EMPTY_REPOSITORY = 409  # the commit lookup of a repository without any commit
_GITHUB_UNKNOWN_REF = 422  # the commit lookup of a ref that names nothing
_TOKEN = re.compile(r"^([0-9a-f]{40}):(\d{1,6})$")


def external_id_of(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:40]


class GitRepositoryConnector:
    kind = CONNECTOR_KIND_GIT_REPOSITORY
    requires_parser = False

    def __init__(
        self, scope: GitScope, *, transport: httpx.AsyncBaseTransport | None = None, label: str | None = None,
        auth: tuple[str, str] | None = None, clone: GitCloneReader | None = None, bearer: str | None = None,
    ) -> None:
        self._scope = scope
        self._clone = clone
        # Files are titled "<repository>:<path>" (``repository_snapshot/labels``).
        self._label = label or scope.location.path.rsplit("/", 1)[-1]
        self._reader = GitHostReader(transport=transport, auth=auth, bearer=bearer)
        self._bearer = bool(bearer)
        self._commit: str | None = None
        self._entries: tuple[SnapshotEntry, ...] = ()
        self._by_id: dict[str, SnapshotEntry] = {}
        self._empty = False

    @property
    def repository_empty(self) -> bool:
        return self._empty

    @property
    def completed_reason(self) -> str | None:
        return REASON_REPOSITORY_EMPTY if self._empty else None

    @property
    def commit(self) -> str | None:
        return self._commit

    @property
    def item_paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self._entries if entry.skip is None)

    async def _load(self, commit: str | None) -> None:
        location, host = self._scope.location, self._scope.location.host
        if host is None:  # pragma: no cover - GitScope.load admits known hosts only
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        if isinstance(host, BitbucketDataCenterHost):
            await self._load_cloned(host, commit)
            return
        github = host is GITHUB
        if commit is None:
            try:
                commit = self._scope.pinned_commit or await self._reader.resolve_commit(
                    host.commit_url(location.path, self._scope.ref), json_key=host.commit_json_key
                )
            except HostStatusError as error:
                if github and error.status == _GITHUB_EMPTY_REPOSITORY:
                    self._commit, self._entries, self._by_id, self._empty = None, (), {}, True  # an empty repository
                    return
                if github and error.status == _GITHUB_UNKNOWN_REF:
                    raise ConnectorError(REASON_SOURCE_NOT_FOUND) from None
                raise
        if commit == self._commit:
            return
        archive = await self._archive(location.path, commit)
        entries = await asyncio.to_thread(read_snapshot, archive, limits=self._scope.limits, strip_top_level=True) \
            if archive else ()
        self._commit, self._entries, self._empty = commit, entries, False
        self._by_id = {external_id_of(entry.path): entry for entry in entries if entry.skip is None}

    async def _archive(self, path: str, commit: str) -> bytes:
        host = self._scope.location.host
        assert host is not None
        try:
            if host is GITHUB and self._bearer:
                archive = await self._reader.archive(
                    host.api_archive_url(path, commit), max_bytes=MAX_ARCHIVE_BYTES,
                    redirect_host=host.archive_base.removeprefix("https://"),
                )
            else:
                archive = await self._reader.archive(host.archive_url(path, commit), max_bytes=MAX_ARCHIVE_BYTES)
        except ConnectorError as error:
            if host is GITHUB and error.reason == REASON_SOURCE_NOT_FOUND and await self._tree_empty(path, commit):
                return b""
            raise
        if not archive and not (host is GITHUB and await self._tree_empty(path, commit)):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return archive

    async def _tree_empty(self, path: str, commit: str) -> bool:
        try:
            tree = await self._reader.json(GITHUB.tree_url(path, commit), max_bytes=MAX_TREE_JSON_BYTES)
        except ConnectorError:
            return False
        return isinstance(tree, dict) and tree.get("tree") == [] and tree.get("truncated") is not True

    async def _load_cloned(self, host: BitbucketDataCenterHost, commit: str | None) -> None:
        if self._clone is None:  # a Data Center repository is read only with its linked connection
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        commit = commit or self._scope.pinned_commit
        if commit is not None and commit == self._commit:
            return
        try:
            sha, archive = await self._clone.snapshot(
                host.clone_url(self._scope.location.path), ref=self._scope.ref, commit=commit,
                max_bytes=MAX_ARCHIVE_BYTES,
            )
        except RepositoryEmptyError:
            # No commit to read: an empty listing that completes the pass.
            self._commit, self._entries, self._by_id, self._empty = None, (), {}, True
            return
        entries = await asyncio.to_thread(read_snapshot, archive, limits=self._scope.limits, strip_top_level=False)
        self._commit, self._entries, self._empty = sha, entries, False
        self._by_id = {external_id_of(entry.path): entry for entry in entries if entry.skip is None}

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        commit, offset = None, 0
        if token is not None:
            match = _TOKEN.fullmatch(token)
            if match is None or not SHA.fullmatch(match[1]):
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
            commit, offset = match[1], int(match[2])
        await self._load(commit)
        if self._empty:
            return ListingPage(items=(), next_token=None)  # also mid-pass: the repository lost every commit
        if offset > len(self._entries):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        items: list[SourceItem] = []
        skipped: list[tuple[str, str]] = []
        index = offset
        while index < len(self._entries) and len(items) < limit and len(skipped) < MAX_SKIPPED_PER_PAGE:
            entry = self._entries[index]
            index += 1
            if entry.skip is not None:
                skipped.append((entry.path[:MAX_REPORTED_PATH_CHARS], entry.skip))
                continue
            items.append(self._item(entry))
        next_token = f"{self._commit}:{index}" if index < len(self._entries) else None
        return ListingPage(items=tuple(items), next_token=next_token, skipped=tuple(skipped))

    def _item(self, entry: SnapshotEntry) -> SourceItem:
        assert self._commit is not None
        return SourceItem(
            external_id=external_id_of(entry.path),
            title=file_title(self._label, entry.path),
            source_url=str(self._scope.location.blob_url(self._commit, entry.path)),
            version_marker=entry.blob_sha,
            acl=AclFacet.scope(),
        )

    async def fetch(self, item: SourceItem) -> ItemContent:
        entry = self._by_id.get(item.external_id)
        if entry is None or entry.data is None or self._commit is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        facet = CodeFileFacet(
            repository=self._scope.location.url,
            path=entry.path,
            language=language_of(entry.path),
            commit=self._commit,
            blob_sha=entry.blob_sha,
        )
        return ItemContent(data=entry.data, media_type="text/plain", code_file=facet)

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        return None  # items carry the Workspace scope (a private repository is read with the Workspace's connection)


__all__ = ["GitRepositoryConnector", "MAX_ARCHIVE_BYTES", "external_id_of"]
