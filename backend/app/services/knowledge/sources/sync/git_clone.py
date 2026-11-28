"""Read one commit of a Bitbucket Server/Data Center repository with ``git`` over HTTPS and a connection's credential.
The clone URL never carries the credential."""

from __future__ import annotations

import asyncio
import gzip
import os
import re
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

import httpx

from app.services.connector_auth.atlassian_modes import SCHEME_BASIC

from ....connector_auth.atlassian import AtlassianCredential
from ....connector_auth.oidc_client_credentials import OidcTokenError
from ....connector_auth.oidc_token_cache import access_token, invalidate
from ....git_http_auth import basic_askpass_env, bearer_header_env
from ....outbound_egress import CONNECTION_BITBUCKET, connection_rule
from ....outbound_egress.target_check import check_connection_target
from ....outbound_url_policy import OutboundURLPolicyError
from .contract import (
    REASON_EGRESS_REFUSED,
    REASON_REPOSITORY_EMPTY,
    REASON_REPOSITORY_TOO_LARGE,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from .git_hosts import SHA

DEFAULT_TIMEOUT_SECONDS = 300.0
_CHUNK = 64 * 1024
# Git's own words for a refused sign-in and an unknown repository or ref (stderr is matched, never reported).
_UNAUTHORIZED = ("authentication failed", "could not read username", "could not read password", " 401", " 403")
_NOT_FOUND = ("not found", "couldn't find remote ref", "does not appear to be a git repository", " 404")
# Hardening of every Git command: only the allowed transport protocols (HTTPS), no redirects.
_SAFE = ("-c", "http.followRedirects=false", "-c", "protocol.allow=never")
_UNSET_ENV = ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_DIR", "GIT_WORK_TREE", "GIT_TERMINAL_PROMPT")

# One advertised ref of ``git ls-remote``: an object id (SHA-1 or SHA-256), a tab, the ref name.
_REF_LINE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})\t\S")
_MAX_LS_REMOTE_BYTES = 1024 * 1024

Run = Callable[[list[str], Mapping[str, str], float, int], Awaitable[tuple[int, bytes, bytes]]]
EgressCheck = Callable[[str], Awaitable[None]]


async def run_git(argv: list[str], env: Mapping[str, str], timeout: float, max_stdout: int) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv, env=dict(env), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _stdout() -> bytes | None:
        chunks, size = [], 0
        assert process.stdout is not None
        while chunk := await process.stdout.read(_CHUNK):
            size += len(chunk)
            if size > max_stdout:
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    try:
        out, err = await asyncio.wait_for(asyncio.gather(_stdout(), process.stderr.read()), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return -1, b"", b""
    if out is None:
        process.kill()
        await process.wait()
        return -2, b"", err
    return await process.wait(), out, err


async def bitbucket_egress_check(url: str) -> None:
    try:
        await check_connection_target(url, connection_rule(CONNECTION_BITBUCKET))
    except OutboundURLPolicyError:
        raise ConnectorError(REASON_EGRESS_REFUSED) from None


class RepositoryEmptyError(ConnectorError):
    def __init__(self) -> None:
        super().__init__(REASON_REPOSITORY_EMPTY)


def advertises_no_ref(ls_remote_stdout: bytes) -> bool:
    for line in ls_remote_stdout.decode("ascii", "replace").splitlines():
        match = _REF_LINE.match(line)
        if match and match[1].strip("0"):
            return False
    return True


def _reason(stderr: bytes) -> str:
    text = stderr.decode("utf-8", "replace").lower()
    if any(marker in text for marker in _UNAUTHORIZED):
        return REASON_SOURCE_UNAUTHORIZED
    if any(marker in text for marker in _NOT_FOUND):
        return REASON_SOURCE_NOT_FOUND
    return REASON_SOURCE_UNAVAILABLE


@dataclass(slots=True)
class GitCloneReader:
    credential: AtlassianCredential = field(repr=False)
    git_token: str | None = field(default=None, repr=False)  # the repository's own token, used instead
    egress_check: EgressCheck | None = None  # default: the ``bitbucket`` egress rule
    run: Run | None = None  # default: :func:`run_git`
    oidc_transport: httpx.AsyncBaseTransport | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    protocols: tuple[str, ...] = ("https",)  # tests add ``http`` for a loopback Git server

    async def _env(self, clone_url: str, workdir: str, *, renew: bool) -> dict[str, str]:
        base = {key: value for key, value in os.environ.items()
                if key not in _UNSET_ENV and not key.startswith("OCTRYX_GIT_")}
        if self.git_token:
            return bearer_header_env(clone_url, self.git_token, base)
        if self.credential.scheme == SCHEME_BASIC:
            return basic_askpass_env(clone_url, self.credential.principal, self.credential.secret,
                                     script_dir=workdir, base=base)
        token = self.credential.secret
        if self.credential.oidc is not None:
            try:
                if renew:
                    invalidate(self.credential.oidc)
                token = await access_token(self.credential.oidc, transport=self.oidc_transport)
            except OidcTokenError:
                raise ConnectorError(REASON_SOURCE_UNAUTHORIZED) from None
        return bearer_header_env(clone_url, token, base)

    async def snapshot(self, clone_url: str, *, ref: str, commit: str | None, max_bytes: int) -> tuple[str, bytes]:
        await (self.egress_check or bitbucket_egress_check)(clone_url)
        workdir = tempfile.mkdtemp(prefix="octryx-git-sync-")
        try:
            for attempt in range(2):
                env = await self._env(clone_url, workdir, renew=attempt > 0)
                try:
                    return await self._snapshot(workdir, env, clone_url, ref, commit, max_bytes)
                except ConnectorError as error:
                    if (error.reason != REASON_SOURCE_UNAUTHORIZED or self.credential.oidc is None or attempt
                            or self.git_token):
                        raise
            raise ConnectorError(REASON_SOURCE_UNAUTHORIZED)  # pragma: no cover - the loop returns or raises
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _git(self, env: Mapping[str, str], *args: str, max_stdout: int = 1024 * 1024) -> tuple[int, bytes, bytes]:
        allowed = [item for protocol in self.protocols for item in ("-c", f"protocol.{protocol}.allow=always")]
        return await (self.run or run_git)(["git", *_SAFE, *allowed, *args], env, self.timeout_seconds, max_stdout)

    async def _snapshot(self, workdir: str, env: Mapping[str, str], clone_url: str, ref: str, commit: str | None,
                        max_bytes: int) -> tuple[str, bytes]:
        repo = os.path.join(workdir, "repo.git")
        code, _, _ = await self._git(env, "init", "--quiet", "--bare", repo)
        if code != 0:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE)
        try:
            fetched = await self._fetch(env, repo, clone_url, commit or ref)
            if commit is not None and fetched != commit and await self._fetch(env, repo, clone_url, ref) != commit:
                # The pass's commit is neither fetchable by itself nor the ref's tip any more.
                raise ConnectorError(REASON_SOURCE_NOT_FOUND)
        except ConnectorError as error:
            if error.reason == REASON_SOURCE_NOT_FOUND and await self._empty(env, clone_url):
                raise RepositoryEmptyError() from None
            raise
        sha = commit or fetched
        code, out, _ = await self._git(env, "--git-dir", repo, "archive", "--format=tar", sha, max_stdout=max_bytes)
        if code == -2:
            raise ConnectorError(REASON_REPOSITORY_TOO_LARGE)
        if code != 0:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE)
        return sha, await asyncio.to_thread(gzip.compress, out, 1)

    async def _empty(self, env: Mapping[str, str], clone_url: str) -> bool:
        code, out, _ = await self._git(env, "ls-remote", clone_url, max_stdout=_MAX_LS_REMOTE_BYTES)
        return code == 0 and advertises_no_ref(out)

    async def _fetch(self, env: Mapping[str, str], repo: str, clone_url: str, want: str) -> str | None:
        code, _, err = await self._git(
            env, "--git-dir", repo, "fetch", "--quiet", "--no-tags", "--depth", "1", clone_url, want,
        )
        if code == -1:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE)
        if code != 0:
            reason = _reason(err)
            if SHA.fullmatch(want) and reason != REASON_SOURCE_UNAUTHORIZED:
                return None  # a server that serves no unadvertised commit: the caller tries the ref
            raise ConnectorError(reason)
        code, out, _ = await self._git(env, "--git-dir", repo, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
        sha = out.decode("ascii", "replace").strip().lower()
        if code != 0 or not SHA.fullmatch(sha):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return sha


__all__ = ["GitCloneReader", "RepositoryEmptyError", "advertises_no_ref", "bitbucket_egress_check", "run_git"]
