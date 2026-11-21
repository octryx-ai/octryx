"""The repository a session reports, checked before it is bound (device parity).

A confirmed change edits only inside the bound root (``capability``), and the run's phase rules, read evidence and
change facts all trust that root. So the binding a launcher reports (``POST sessions/repository``, the interactive
launcher and a device job alike) is checked before ``bind_session_repository`` records it:

- **a device session** (the gateway grant belongs to a registered device, ``OAuthGrant.device_id``): the root must
  lie inside one of the device's allowed folders as it last reported them (``UserDevice.folders``), else
  ``denied: folder_not_allowed_on_device``; a device session that reports no root is ``denied:
  repository_root_missing``;
- **a run-bound session** (a device job's session bound at registration, or a terminal attached to its Work item's
  run): the folder's git remote must be the run's repository on the Workspace's connection for that provider — the
  connection's host and the run's ``<owner>/<repo>`` path, case-insensitive (Bitbucket Server's ``scm/`` prefix is
  not part of the path) — else ``denied: repository_not_run_repository``. A run without a repository is not
  checked (the allowed folder is its repository); a connection without a URL to compare with is
  ``needs_configuration: run_repository_unverifiable``.

The run check also runs when a session that already has a binding attaches to a run (``workflow_runs.octryx.attach``),
so the order of binding and attaching never skips it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, WorkflowRun
from ...models.security.device import DEVICE_STATUS_ACTIVE, UserDevice
from ...models.security.oauth_provider import OAuthGrant
from ..devices.dispatch_gate import folder_allowlisted, normalized_folder
from ..knowledge.sources.repository_snapshot.binding import SnapshotRefusal, session_binding
from ..knowledge.sources.repository_snapshot.remote import RemoteRefusedError, parse_remote
from ..knowledge.sources.sync.git_hosts import RepositoryLocation

REASON_FOLDER_NOT_ALLOWED = "folder_not_allowed_on_device"
REASON_ROOT_MISSING = "repository_root_missing"
REASON_NOT_RUN_REPOSITORY = "repository_not_run_repository"
REASON_RUN_REPOSITORY_UNVERIFIABLE = "run_repository_unverifiable"
MESSAGES = {
    REASON_FOLDER_NOT_ALLOWED: "The repository root is not inside one of the device's allowed folders.",
    REASON_ROOT_MISSING: "A device session must report the repository root of its job folder.",
    REASON_NOT_RUN_REPOSITORY: "The folder's git remote is not the run's repository on the Workspace's connection.",
    REASON_RUN_REPOSITORY_UNVERIFIABLE: "The run's repository or its connection URL is not set, so the folder's "
                                        "repository cannot be verified.",
}
# The connection fields that name where each provider serves its repositories (API, web or clone URL).
_HOST_FIELDS = {
    "github": ("github_url", "github_web_url", "github_clone_base_url"),
    "gitlab": ("gitlab_url",),
    "bitbucket": ("bitbucket_url",),
}
_DEFAULT_HOSTS = {"github": "github.com"}
# API hosts whose repositories are cloned from the web host.
_HOST_ALIASES = {"api.github.com": "github.com", "api.bitbucket.org": "bitbucket.org"}


def _host(url: object) -> str:
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower() if parts.scheme in ("http", "https", "ssh") else ""
    return _HOST_ALIASES.get(host, host)


async def connection_hosts(db: AsyncSession, run: WorkflowRun, provider: str, repo_args: dict[str, Any]) -> set[str]:
    """The hosts of the connection the run's source-control actions on this repository run on."""
    from ..workflow_runs.platform.bitbucket_cloud import serving_config
    from ..workflow_runs.platform.repo_ref import TOOLS

    config = await serving_config(db, run, repo_args, tool_name=TOOLS[provider]["pr"])
    hosts = {_host(config.get(field)) for field in _HOST_FIELDS[provider]} - {""}
    if not str(config.get(_HOST_FIELDS[provider][0]) or "").strip() and provider in _DEFAULT_HOSTS:
        hosts.add(_DEFAULT_HOSTS[provider])
    return hosts


def _repository_path(provider: str, location: RepositoryLocation) -> str:
    segments = location.path.lower().split("/")
    if provider == "bitbucket" and "scm" in segments[:-2]:
        segments = segments[segments.index("scm") + 1:]  # Bitbucket Server clones from <context>/scm/<key>/<slug>
    return "/".join(segments)


async def run_repository_refusal(db: AsyncSession, run: WorkflowRun, location: RepositoryLocation
                                 ) -> SnapshotRefusal | None:
    """``None`` when ``location`` is the run's repository on the Workspace's connection."""
    from ..workflow_runs.platform.repo_ref import parse_repository

    ref = parse_repository(run.repository)
    if ref is None:
        # A run that names no repository has nothing to compare with: the folder (already inside the device's allowed
        # folders) is the work's repository. Refusing here would stop every run started without a repository; a
        # team that wants the check names the repository when it starts the run.
        return None
    hosts = await connection_hosts(db, run, ref.provider, ref.args())
    if not hosts:
        return SnapshotRefusal("needs_configuration", REASON_RUN_REPOSITORY_UNVERIFIABLE)
    if location.hostname.lower() not in hosts or _repository_path(ref.provider, location) != ref.path.lower():
        return SnapshotRefusal("denied", REASON_NOT_RUN_REPOSITORY)
    return None


async def device_folder_refusal(db: AsyncSession, *, grant_id: str, user_id: str, root: object
                                ) -> SnapshotRefusal | None:
    """For a device's grant: the root must lie inside the device's allowed folders. Other grants: ``None``."""
    grant = await db.get(OAuthGrant, grant_id) if grant_id else None
    device_id = getattr(grant, "device_id", None)
    if not device_id:
        return None
    device = await db.get(UserDevice, device_id)
    if device is None or device.status != DEVICE_STATUS_ACTIVE or device.owner_user_id != user_id:
        return SnapshotRefusal("denied", REASON_FOLDER_NOT_ALLOWED)
    if root is None:
        return SnapshotRefusal("denied", REASON_ROOT_MISSING)
    folder = normalized_folder(root)
    if not folder or not folder_allowlisted(folder, list(device.folders or [])):
        return SnapshotRefusal("denied", REASON_FOLDER_NOT_ALLOWED)
    return None


async def binding_refusal(db: AsyncSession, *, session: Session, grant_id: str, user_id: str,
                          payload: dict[str, Any]) -> SnapshotRefusal | None:
    """The refusal of a reported binding before it is recorded; ``None`` lets ``bind_session_repository`` decide."""
    from ..workflow_runs.records import active_run_for_session

    refused = await device_folder_refusal(db, grant_id=grant_id, user_id=user_id, root=payload.get("root"))
    if refused is not None:
        return refused
    run = await active_run_for_session(db, session.id)
    if run is None:
        return None
    try:
        location = parse_remote(payload.get("remote_url"))
    except RemoteRefusedError:
        return None  # the binding refuses an invalid remote with its own reason
    return await run_repository_refusal(db, run, location)


async def bound_repository_refusal(db: AsyncSession, run: WorkflowRun, session: Session) -> SnapshotRefusal | None:
    """A session's existing binding checked against a run it attaches to; ``None`` without a binding."""
    binding = session_binding(session)
    if not binding or not binding.get("remote"):
        return None
    try:
        location = parse_remote(binding["remote"])
    except RemoteRefusedError:
        return SnapshotRefusal("denied", REASON_NOT_RUN_REPOSITORY)
    return await run_repository_refusal(db, run, location)


__all__ = [
    "MESSAGES",
    "REASON_FOLDER_NOT_ALLOWED",
    "REASON_NOT_RUN_REPOSITORY",
    "REASON_ROOT_MISSING",
    "REASON_RUN_REPOSITORY_UNVERIFIABLE",
    "binding_refusal",
    "bound_repository_refusal",
    "connection_hosts",
    "device_folder_refusal",
    "run_repository_refusal",
]
