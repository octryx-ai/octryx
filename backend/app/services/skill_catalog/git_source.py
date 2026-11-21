"""Read-only access to a skill's Git repository: resolve a ref, list the tree, read selected files.

Every fetch is shallow (``--depth 1``) and blob-filtered; files are materialised with a sparse checkout of only
the requested paths. Submodules are never fetched, LFS is never run (pointer files are refused), hooks never run
(``core.hooksPath=/dev/null``), symlinks are never followed (refused from the tree listing, ``core.symlinks``
off), redirects are not followed, and only HTTPS is allowed. The host must be on the instance allowlist
(``settings.allowed_hosts``) and pass ``outbound_url_policy`` before each network command. A token from a named
connection travels in ``http.extraHeader`` through ``GIT_CONFIG_*`` environment variables, never in argv.

:func:`set_git_fetcher` installs another :class:`GitFetcher` (tests use an in-memory one); nothing in the tests
reaches the network.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from ..outbound_url_policy import OutboundURLPolicyError, check_outbound_target
from .bundle import MAX_FILE_BYTES
from .errors import SkillCatalogError

MODE_FILE = "100644"
MODE_EXECUTABLE = "100755"
MODE_SYMLINK = "120000"
MODE_SUBMODULE = "160000"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MAX_TREE_ENTRIES = 100_000
COMMAND_TIMEOUT_SECONDS = 90
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"


@dataclass(frozen=True, slots=True)
class TreeEntry:
    path: str
    mode: str


@dataclass(slots=True)
class RepoSnapshot:
    """One commit of a repository: every path with its Git mode, and the files read so far."""

    url: str
    commit: str
    entries: dict[str, TreeEntry]
    reader: SnapshotReader | None = None
    cache: dict[str, bytes] = field(default_factory=dict)

    def paths(self) -> list[str]:
        return sorted(self.entries)

    async def read_many(self, paths: list[str]) -> dict[str, bytes]:
        wanted = [path for path in paths if path not in self.cache]
        for path in wanted:
            entry = self.entries.get(path)
            if entry is None:
                raise SkillCatalogError("skill_source_path_missing", 422, path=path)
            if entry.mode == MODE_SYMLINK:
                raise SkillCatalogError("skill_archive_symlink", 422, path=path,
                                        message="Symbolic links are not allowed.")
            if entry.mode == MODE_SUBMODULE:
                raise SkillCatalogError("skill_source_submodule", 422, path=path,
                                        message="Submodules are not imported.")
        if wanted and self.reader is not None:
            self.cache.update(await self.reader.read(wanted))
        for path in wanted:
            data = self.cache.get(path)
            if data is None:
                raise SkillCatalogError("skill_source_path_missing", 422, path=path)
            if data.startswith(LFS_POINTER_PREFIX):
                raise SkillCatalogError("skill_source_lfs_pointer", 422, path=path,
                                        message="Git LFS files are not imported.")
        return {path: self.cache[path] for path in paths}


class SnapshotReader(Protocol):
    async def read(self, paths: list[str]) -> dict[str, bytes]: ...


class GitFetcher(Protocol):
    async def resolve(self, url: str, ref: str, *, token: str | None) -> str: ...

    def open(self, url: str, commit: str, *, token: str | None) -> AsyncIterator[RepoSnapshot]: ...


def normalize_repository_url(url: str, allowed_hosts: tuple[str, ...], *, schemes: tuple[str, ...] = ("https",)
                             ) -> str:
    """``https://host/owner/repo`` (no credentials, query or fragment) on an allowed host, else refused."""
    text = str(url or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in schemes or (parts.scheme == "https" and not parts.hostname):
        raise SkillCatalogError("skill_source_url_invalid", 422, message="Use an https:// repository URL.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SkillCatalogError("skill_source_url_invalid", 422,
                                message="The URL may not carry credentials, a query or a fragment.")
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host not in allowed_hosts:
        raise SkillCatalogError("skill_source_host_not_allowed", 422, host=host,
                                message="Add the host to the allowed hosts in Sources & updates first.")
    path = parts.path.rstrip("/")
    if parts.scheme == "https" and not re.match(r"^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$", path):
        raise SkillCatalogError("skill_source_url_invalid", 422, message="Use https://host/owner/repository.")
    return f"{parts.scheme}://{parts.netloc.lower()}{path}" if parts.scheme == "https" else text.rstrip("/")


def normalize_repo_path(path: str) -> str:
    text = str(path or "").strip().strip("/")
    if not text:
        return ""
    if ".." in text.split("/") or "\\" in text or any(ord(char) < 32 for char in text):
        raise SkillCatalogError("skill_source_path_invalid", 422)
    return text


class SubprocessGitFetcher:
    """The real fetcher: ``git`` in a private temporary directory, one per snapshot."""

    def __init__(self, *, protocols: tuple[str, ...] = ("https",), check_outbound: bool = True) -> None:
        self._protocols = protocols
        self._check_outbound = check_outbound

    def _env(self, home: str, token: str | None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_ALLOW_PROTOCOL": ":".join(self._protocols),
            "LC_ALL": "C",
        }
        config = [("core.hooksPath", "/dev/null"), ("core.symlinks", "false"), ("protocol.allow", "never"),
                  ("http.followRedirects", "false"), ("submodule.recurse", "false"),
                  ("filter.lfs.smudge", ""), ("filter.lfs.process", ""), ("filter.lfs.required", "false"),
                  *((f"protocol.{name}.allow", "always") for name in self._protocols)]
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            config.append(("http.extraHeader", f"Authorization: Basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(config))
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
        return env

    async def _admit(self, url: str) -> None:
        if not self._check_outbound or not url.startswith("https://"):
            return
        try:
            await check_outbound_target(url)
        except OutboundURLPolicyError as error:
            raise SkillCatalogError("skill_source_host_refused", 422, reason=error.reason) from None

    async def _git(self, args: list[str], *, cwd: str, env: dict[str, str]) -> bytes:
        def run() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                                  timeout=COMMAND_TIMEOUT_SECONDS, check=False)

        try:
            completed = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired:
            raise SkillCatalogError("skill_source_timeout", 504) from None
        if completed.returncode != 0:
            # Git's own message, first line only, for the admin; the token never reaches stderr (header via env).
            first = completed.stderr.decode("utf-8", "replace").strip().splitlines()[:1]
            raise SkillCatalogError("skill_source_fetch_failed", 502, command=args[0],
                                    git_error=(first[0] if first else "")[:200])
        return completed.stdout

    async def resolve(self, url: str, ref: str, *, token: str | None) -> str:
        wanted = str(ref or "HEAD").strip()
        if COMMIT_PATTERN.match(wanted):
            return wanted
        await self._admit(url)
        home = tempfile.mkdtemp(prefix="octryx-skill-git-")
        try:
            output = await self._git(["ls-remote", "--", url, wanted, f"refs/heads/{wanted}", f"refs/tags/{wanted}"],
                                     cwd=home, env=self._env(home, token))
        finally:
            shutil.rmtree(home, ignore_errors=True)
        lines = [line.split("\t", 1) for line in output.decode().splitlines() if "\t" in line]
        refs = {name: sha for sha, name in lines}
        for candidate in (f"refs/heads/{wanted}", f"refs/tags/{wanted}^{{}}", f"refs/tags/{wanted}", wanted):
            if candidate in refs and COMMIT_PATTERN.match(refs[candidate]):
                return refs[candidate]
        raise SkillCatalogError("skill_source_ref_not_found", 422, ref=wanted)

    @asynccontextmanager
    async def open(self, url: str, commit: str, *, token: str | None) -> AsyncIterator[RepoSnapshot]:
        if not COMMIT_PATTERN.match(commit):
            raise SkillCatalogError("skill_source_commit_invalid", 422)
        await self._admit(url)
        home = tempfile.mkdtemp(prefix="octryx-skill-git-")
        repo = str(Path(home) / "repo")
        env = self._env(home, token)
        try:
            os.makedirs(repo)
            await self._git(["init", "-q"], cwd=repo, env=env)
            await self._git(["remote", "add", "origin", url], cwd=repo, env=env)
            await self._git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "--no-tags",
                             "--no-recurse-submodules", "origin", commit], cwd=repo, env=env)
            listing = await self._git(["ls-tree", "-r", "-z", "--full-tree", commit], cwd=repo, env=env)
            entries: dict[str, TreeEntry] = {}
            for record in listing.split(b"\0"):
                if not record:
                    continue
                meta, _, raw_path = record.partition(b"\t")
                mode = meta.split(b" ", 1)[0].decode()
                path = raw_path.decode("utf-8", "replace")
                entries[path] = TreeEntry(path, mode)
                if len(entries) > MAX_TREE_ENTRIES:
                    raise SkillCatalogError("skill_source_too_large", 422)
            yield RepoSnapshot(url=url, commit=commit, entries=entries,
                               reader=_CheckoutReader(self, repo, commit, env))
        finally:
            shutil.rmtree(home, ignore_errors=True)


class _CheckoutReader:
    def __init__(self, fetcher: SubprocessGitFetcher, repo: str, commit: str, env: dict[str, str]) -> None:
        self._fetcher, self._repo, self._commit, self._env = fetcher, repo, commit, env

    async def read(self, paths: list[str]) -> dict[str, bytes]:
        patterns = [f"/{path}" for path in paths]
        await self._fetcher._git(["sparse-checkout", "set", "--no-cone", "--", *patterns], cwd=self._repo,
                                 env=self._env)
        await self._fetcher._git(["checkout", "-q", "--detach", self._commit], cwd=self._repo, env=self._env)
        result: dict[str, bytes] = {}
        root = Path(self._repo).resolve()
        for path in paths:
            target = (root / path).resolve()
            if root not in target.parents or not target.is_file() or target.is_symlink():
                continue
            if target.stat().st_size > MAX_FILE_BYTES:
                raise SkillCatalogError("skill_file_too_large", 422, path=path)
            result[path] = target.read_bytes()
        return result


_FETCHER: GitFetcher = SubprocessGitFetcher()


def git_fetcher() -> GitFetcher:
    return _FETCHER


def set_git_fetcher(fetcher: GitFetcher | None) -> None:
    global _FETCHER
    _FETCHER = fetcher if fetcher is not None else SubprocessGitFetcher()


__all__ = [
    "MODE_EXECUTABLE",
    "MODE_FILE",
    "MODE_SUBMODULE",
    "MODE_SYMLINK",
    "GitFetcher",
    "RepoSnapshot",
    "SubprocessGitFetcher",
    "TreeEntry",
    "git_fetcher",
    "normalize_repo_path",
    "normalize_repository_url",
    "set_git_fetcher",
]
