"""Read one commit of a Bitbucket Server/Data Center repository with ``git`` over HTTPS and a connection's credential.

A Data Center repository has no anonymous archive URL: the ``git_repository`` connector reads it the way the
Bitbucket tools clone, with the source's linked connection (``git_bitbucket.py``):

1. the clone URL (``<base>/scm/<key>/<slug>.git``, never carrying a credential) passes the egress rule of the
   ``bitbucket`` connection type first (``public_only`` plus the admin's on-prem allowlist); a refusal is
   ``egress_refused`` and Git never starts;
2. the credential reaches Git through its environment only (``services/git_http_auth.py``): a Bearer token
   (``bearer_pat``, or the access token of the OpenID Connect client credentials grant) as
   ``http.<origin>/.extraHeader`` via ``GIT_CONFIG_*``; a username and password through an askpass script that
   reads them from the environment. Never in argv, the remote URL or a file; credential helpers are cleared and Git
   never prompts;
3. ``git fetch --depth 1`` of the ref (or of the pass's commit) into a temporary bare repository, without
   following redirects and over HTTPS only; ``git archive`` of that commit is the snapshot (``git_snapshot.py``).

Every failure is a fixed reason (``source_unauthorized``, ``source_not_found``, ``source_unavailable``,
``repository_too_large``): Git's output is never logged or reported. An ``oidc`` token refused with a 401 is renewed
and the fetch retried once, as the HTTP clients do (``OidcBearerAuth``).

**An empty repository is no failure**. A Data Center repository without a commit has no branch and
no default branch, so the fetch of its ref answers "couldn't find remote ref". Only then, with the same credential,
``git ls-remote`` asks the server what it has: a reachable repository that advertises **no ref at all** (no head, no
tag) is ``repository_empty`` (:class:`RepositoryEmptyError`); a missing repository fails ``ls-remote`` itself, and a
repository with refs but not the configured one stays ``source_not_found``.

A repository with its own Git token (``git_token``; Data Center answers 500 on ``/scm/`` for the
OpenID Connect token; ``knowledge/sources/repository_git_token.py``) gets that token as the Bearer header instead of
the connection's sign-in, and nothing is renewed or retried with another credential.
"""

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

from app.services.atlassian_auth_modes import SCHEME_BASIC

from ....atlassian_auth import AtlassianCredential
from ....git_http_auth import basic_askpass_env, bearer_header_env
from ....oidc_client_credentials import OidcTokenError
from ....oidc_token_cache import access_token, invalidate
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
    """Run ``argv`` with ``env``; stdout is bounded (``-2`` when it passed ``max_stdout``), a timeout is ``-1``."""
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
    """The ``bitbucket`` connection type's egress rule for ``url``; raises ``egress_refused``."""
    try:
        await check_connection_target(url, connection_rule(CONNECTION_BITBUCKET))
    except OutboundURLPolicyError:
        raise ConnectorError(REASON_EGRESS_REFUSED) from None


class RepositoryEmptyError(ConnectorError):
    """The repository exists and answers, but advertises no ref: nothing to read yet (no failure, module doc)."""

    def __init__(self) -> None:
        super().__init__(REASON_REPOSITORY_EMPTY)


def advertises_no_ref(ls_remote_stdout: bytes) -> bool:
    """True when ``git ls-remote``'s output names no ref (an all-zero id, a capabilities placeholder, is none)."""
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
    """Snapshots of one Data Center repository with exactly ``credential`` (see the module doc)."""

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
        """``(commit, gzip tarball of its tree)``: ``ref``'s tip, or ``commit`` when the pass already fixed one."""
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
        """The repository answered ``ls-remote`` (it exists, the credential reads it) and advertises no ref."""
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
