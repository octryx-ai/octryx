"""The ``git_repository`` Source Sync connector in its ``remote_git`` fetch mode.

A listing pass reads one commit of a public repository on a known host:

1. at the pass start, ``ref`` resolves to a commit sha once (a configured full sha is used as is);
   every later page of the same pass carries that sha in its token (``<sha>:<offset>``), so a pass
   that spans several bounded runs never mixes two commits;
2. the host's archive at that sha is fetched over the pinned ``git_repository`` egress transport
   (``git_http.py``) and classified (``git_snapshot.py``);
3. pages walk the sorted file list: items become ``SourceItem`` headers, every skipped file is
   reported with its closed outcome (``excluded``, ``skipped_too_large``, ``skipped_binary``, ...).

Per file: ``external_id`` is ``sha256(path)[:40]``, the display title is the path, the version
marker is the git blob sha1, and the source URL is the host blob at the commit
(``https://github.com/<owner>/<repo>/blob/<sha>/<path>``). The runner therefore reports a re-sync of
the same commit as ``unchanged`` without a fetch. ``fetch`` hands the file to ingestion as code
(``ItemContent.code_file``) with its repository, path, language, commit and blob facets.

A Bitbucket Server/Data Center repository has no archive URL: its commit is fetched with ``git`` and the
linked connection's credential (``git_clone.py``), and the same classification reads ``git archive``'s tree.

A Data Center repository **without any commit** lists no item and ends its pass: the run completes
with 0 items and the reason ``repository_empty`` (:attr:`GitRepositoryConnector.completed_reason`), never as a
failure. Its first commit is listed by the next run.

GitHub the same way (a private repository with two commits and no file must not end
``source_not_found``), decided by GitHub's own status codes, never by a message text:

- a repository without any commit answers the commit lookup ``409`` (GitHub: "Git Repository is empty"): the run
  completes as ``repository_empty``, as above;
- a commit whose tree has no file is an empty snapshot *at that commit*: when the archive is not served (``404``) or
  arrives empty, the tree of the commit is read (``git/trees/<sha>``) and an answer ``200`` with no entry lists no
  item. The run completes without a reason and records the commit (``head_commit``), so the source can be set up
  for code navigation and a run can branch from it;
- a ref that names nothing while the repository has commits (``422``), a missing repository or one the reader may
  not see (``404``) stay failures (``source_not_found``, ``source_unauthorized``).

A GitHub repository read through a GitHub connection with a token (``git_bitbucket.linked_git_connection``) sends
the token to ``api.github.com`` only; its archive comes from the API's redirect to ``codeload.github.com``, fetched
without the token (``git_http.py``).

Every item has the scope-wide audience (a repository read through a connection is visible to the Workspace that
registered it), and nothing an item carries holds a credential.
"""

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
        """The repository has no commit yet (``git_clone.RepositoryEmptyError``): this run listed nothing."""
        return self._empty

    @property
    def completed_reason(self) -> str | None:
        """The fixed reason a completed run of this connector carries (``repository_empty``), else ``None``."""
        return REASON_REPOSITORY_EMPTY if self._empty else None

    @property
    def commit(self) -> str | None:
        """The commit this run listed, once a page was read."""
        return self._commit

    @property
    def item_paths(self) -> tuple[str, ...]:
        """Every file of the listed commit that is an item (not skipped), in path order."""
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
                    self._commit, self._entries, self._by_id, self._empty = None, (), {}, True  # module doc
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
        """The archive at ``commit``; ``b""`` for a GitHub commit whose tree has no entry (module doc)."""
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
        """GitHub answers the commit's tree ``200`` with no entry (any other answer: not known to be empty)."""
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
            # No commit to read: an empty listing that completes the pass (module doc).
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
