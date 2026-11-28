"""The capability a governed session gets outside a workflow run: its working root, permission mode and class."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.tools.capability_requirements import CAPABILITY_DELIVER, CAPABILITY_READ_ONLY

from ...models import Session

EFFECTIVE_CAPABILITY_METADATA = "effective_capability"


@dataclass(frozen=True, slots=True)
class EffectiveCapability:
    capability_class: str
    workflow_key: str | None = None
    approval_id: str | None = None
    root: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "class": self.capability_class,
            "workflow_key": self.workflow_key,
            "approval_id": self.approval_id,
        }


def _bound_root(session: Session) -> str | None:
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    binding = metadata.get("repository_binding")
    root = binding.get("root") if isinstance(binding, dict) else None
    return root if isinstance(root, str) and root.startswith("/") else None


SESSION_ROOT_METADATA = "session_root"
PERMISSION_MODE_METADATA = "permission_modes_seen"
PERMISSION_MODES = frozenset({"default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"})
# Never a working root, so a session started there only reads (home, volumes, temp, system).
_NOT_PROJECT_ROOTS = ("/", "/Users", "/home", "/Volumes", "/tmp", "/private", "/private/tmp", "/private/var", "/var",
                      "/etc", "/opt", "/usr", "/Library", "/System", "/Applications")


_SYSTEM_TOP_LEVEL = frozenset({"etc", "opt", "usr", "bin", "sbin", "Library", "System", "Applications", "private",
                               "var", "tmp", "dev", "cores", "Network"})


def _mode(hook_input: dict[str, Any] | None) -> str:
    mode = str((hook_input or {}).get("permission_mode") or "default")
    return mode if mode in PERMISSION_MODES else "default"  # an unknown value counts as the default


def _home_of(hook_input: dict[str, Any] | None) -> str:
    path = str((hook_input or {}).get("transcript_path") or "")
    marker = path.find("/.claude")
    return posixpath.normpath(path[:marker]) if marker > 0 else ""


def project_folder(cwd: str, hook_input: dict[str, Any] | None = None) -> str | None:
    if not cwd.startswith("/"):
        return None
    folder = posixpath.normpath(cwd)
    home = _home_of(hook_input)
    parts = [part for part in folder.split("/") if part]
    if folder in _NOT_PROJECT_ROOTS or folder == home or len(parts) < 2:
        return None
    if parts[0] in {"Users", "home", "Volumes"} and len(parts) < 3:
        return None  # a home folder or a disk, even without a transcript path
    if parts[0] in _SYSTEM_TOP_LEVEL:
        return None  # a system prefix at any depth: /etc/x, /opt/homebrew, /usr/local/x, /Library/x, /private/x
    # Directly under a home folder: ~/Library and dot folders (~/.ssh, ~/.config, ~/.claude) never become a root.
    under_home = folder[len(home) + 1:].split("/")[0] if home and folder.startswith(home + "/") else (
        parts[2] if parts[0] in {"Users", "home"} and len(parts) >= 3 else "")
    if under_home == "Library" or under_home.startswith("."):
        return None
    return folder


def _session_root(session: Session, hook_input: dict[str, Any] | None) -> str | None:
    bound = _bound_root(session)
    if bound is not None:
        return bound
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    stored = metadata.get(SESSION_ROOT_METADATA)
    if isinstance(stored, str) and stored.startswith("/"):
        return stored
    return project_folder(str((hook_input or {}).get("cwd") or ""), hook_input)


async def effective_capability(db: AsyncSession, *, session: Session, session_key: str,
                               hook_input: dict[str, Any] | None = None,
                               free_sessions: str = "follow_permission_mode") -> EffectiveCapability:
    mode = _mode(hook_input)
    root = _session_root(session, hook_input)
    if free_sessions == "read_only" or mode == "plan" or root is None:
        # No project folder (started in home, temp, ...): the session reads until it works in a project.
        best = EffectiveCapability(CAPABILITY_READ_ONLY, root=_bound_root(session))
    else:
        best = EffectiveCapability(CAPABILITY_DELIVER, root=root)
    metadata = dict(session.metadata_ or {})
    seen = list(metadata.get(PERMISSION_MODE_METADATA) or [])
    if mode not in seen:  # which modes a session ran in, for a later incident
        metadata[PERMISSION_MODE_METADATA] = [*seen, mode][:6]
        session.metadata_ = metadata
        flag_modified(session, "metadata_")
    if root is not None and not _bound_root(session) and metadata.get(SESSION_ROOT_METADATA) != root:
        metadata[SESSION_ROOT_METADATA] = root
        session.metadata_ = metadata
        flag_modified(session, "metadata_")
    if metadata.get(EFFECTIVE_CAPABILITY_METADATA) != best.as_metadata():
        metadata[EFFECTIVE_CAPABILITY_METADATA] = best.as_metadata()
        session.metadata_ = metadata
        flag_modified(session, "metadata_")
        await db.flush()
    return best


__all__ = ["EFFECTIVE_CAPABILITY_METADATA", "EffectiveCapability", "effective_capability", "project_folder"]
