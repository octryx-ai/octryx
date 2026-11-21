"""The identity and the links of one git repository, from the launcher's remote URL (C-MCP).

The launcher sends the remote of the user's checkout. It is untrusted input, so only a closed set
of forms is accepted, and never one with credentials:

- ``https://host/owner/repo(.git)`` without userinfo;
- ``ssh://[user@]host/owner/repo(.git)`` without a password;
- the scp form ``user@host:owner/repo(.git)``.

A remote with a password or token is refused (``remote_url_has_credentials``), never cleaned. The
client already strips userinfo, so one that arrives here comes from a misbehaving client.

Every form is normalized to ``https://<host>/<path>`` and then validated by the one repository URL
rule of the source model (``sync/git_hosts.parse_repository_url``, any host). A local snapshot
connector therefore stores exactly the ``remote`` form a ``remote_git`` connector stores. Host
links come from that module's closed host table (``RepositoryLocation.blob_url``); any other host
gets the platform's own source viewer (:func:`platform_blob_url`).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote, urlsplit

from ...episodes.policy import public_origin
from ...ledger.errors import InvalidEvidenceRequestError
from ..sync.git_hosts import RepositoryLocation, parse_repository_url

MAX_REMOTE_CHARS = 512
_SCP = re.compile(r"^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+):([A-Za-z0-9._~/-]+)$")

REASON_REMOTE_MISSING = "repository_remote_missing"
REASON_REMOTE_INVALID = "repository_remote_invalid"
REASON_REMOTE_HAS_CREDENTIALS = "remote_url_has_credentials"


class RemoteRefusedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _host_and_path(value: str) -> tuple[str, str]:
    scp = _SCP.match(value)
    if scp is not None:
        return scp.group(1), scp.group(2)
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme in {"http", "https"}:
        if parts.username is not None or parts.password is not None:
            raise RemoteRefusedError(REASON_REMOTE_HAS_CREDENTIALS)
    elif scheme == "ssh":
        # An ssh user name is no credential (``git@``, ``alice@``); a password is.
        if parts.password is not None:
            raise RemoteRefusedError(REASON_REMOTE_HAS_CREDENTIALS)
    else:
        raise RemoteRefusedError(REASON_REMOTE_INVALID)
    if parts.query or parts.fragment or not parts.hostname:
        raise RemoteRefusedError(REASON_REMOTE_INVALID)
    return parts.hostname, parts.path


def parse_remote(raw: object) -> RepositoryLocation:
    """The repository of ``raw`` in the source model's form, or :class:`RemoteRefusedError`."""
    if raw is None or (type(raw) is str and not raw.strip()):
        raise RemoteRefusedError(REASON_REMOTE_MISSING)
    if type(raw) is not str or len(raw) > MAX_REMOTE_CHARS or any(ch.isspace() for ch in raw.strip()):
        raise RemoteRefusedError(REASON_REMOTE_INVALID)
    host, path = _host_and_path(raw.strip())
    path = path.strip("/")
    path = path[:-4] if path.endswith(".git") else path
    try:
        return parse_repository_url(f"https://{host.lower()}/{path}", known_host_only=False)
    except InvalidEvidenceRequestError:
        raise RemoteRefusedError(REASON_REMOTE_INVALID) from None


def snapshot_connector_key(location: RepositoryLocation) -> str:
    """The connector key a launcher's first snapshot of this repository creates."""
    return "repo-" + hashlib.sha256(location.slug.lower().encode("utf-8")).hexdigest()[:12]


def platform_blob_url(
    origin: str | None,
    workspace_id: str,
    connector_key: str,
    commit: str,
    path: str,
    line: int | None = None,
    blob_sha: str | None = None,
) -> str | None:
    """The platform source viewer's link; ``None`` when no public origin is configured.

    ``blob_sha`` pins the exact content, so the link keeps working after the path changes.
    """
    if not origin:
        return None
    url = (
        f"{origin}/api/v1/workspaces/{workspace_id}/knowledge/repositories/{connector_key}"
        f"/blob/{commit}/{quote(path, safe='/')}"
    )
    if blob_sha:
        url = f"{url}?blob={blob_sha}"
    return f"{url}#L{line}" if line else url


def repository_location_link(
    repository: Any, workspace_id: str, path: str, line: int, blob_sha: str | None = None
) -> str | None:
    """A location of a repository source: the host blob when it is faithful, else the platform viewer.

    ``repository`` is a resolved ``code/codebase.RepositorySource``. Its ``blob_link`` answers only
    for content the host serves exactly (``remote_git``, or a clean, pushed snapshot on a known host).
    """
    link = repository.blob_link(path, line)
    if link is not None or not repository.head_commit:
        return link
    return platform_blob_url(
        public_origin(), workspace_id, repository.connector_key, repository.head_commit, path, line, blob_sha
    )


__all__ = [
    "REASON_REMOTE_HAS_CREDENTIALS",
    "REASON_REMOTE_INVALID",
    "REASON_REMOTE_MISSING",
    "RemoteRefusedError",
    "parse_remote",
    "platform_blob_url",
    "repository_location_link",
    "snapshot_connector_key",
]
