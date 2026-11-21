"""Whether a Workspace accepts session episodes, and where their citations link to.

Both are explicit configuration, and both default to "no":

- **The Workspace switch** ``projects.config.knowledge_episode_policy.accept_session_episodes``. It is
  read from the Workspace row itself, never from the merged turn configuration (agent-writable
  entries are merged into that one), and only an explicit ``true`` enables it. A Workspace admin or
  owner sets it. Without it, an episode write is ``needs_configuration``.
- **Automatic capture of platform chat turns**
  ``knowledge_episode_policy.capture_platform_turns``, a sub-setting of the switch above: only when
  both are an explicit ``true`` does a completed platform chat turn write or update its session's
  episode (``turn_capture.py``). Accepting episodes alone never captures anything automatically.
- **The platform's public origin** (``platform_public_origin`` / ``OCTRYX_PUBLIC_ORIGIN``).
  Every citation must carry a link a person can open, so an episode without an absolute session link
  is not written: the state is ``needs_configuration``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....config import get_settings
from ....models import AuditLog, Project

EPISODE_POLICY_KEY = "knowledge_episode_policy"
POLICY_AUDIT_ACTION = "knowledge.episode_policy.update"
ACCEPT_SESSION_EPISODES = "accept_session_episodes"
CAPTURE_PLATFORM_TURNS = "capture_platform_turns"
# Who may return a session episode once the Workspace accepts them; anything else is denied.
EPISODE_WRITER_ROLES = frozenset({"member", "admin", "owner"})


def _policy_of(config: object) -> dict:
    policy = config.get(EPISODE_POLICY_KEY) if isinstance(config, dict) else None
    return policy if isinstance(policy, dict) else {}


def episodes_accepted_by(config: object) -> bool:
    return _policy_of(config).get(ACCEPT_SESSION_EPISODES) is True


def platform_turn_capture_by(config: object) -> bool:
    """Both switches explicitly ``true``; the sub-setting alone never enables capture."""
    policy = _policy_of(config)
    return policy.get(ACCEPT_SESSION_EPISODES) is True and policy.get(CAPTURE_PLATFORM_TURNS) is True


async def _workspace_config(db: AsyncSession, project_id: str) -> object:
    return (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()


async def episodes_accepted(db: AsyncSession, project_id: str) -> bool:
    return episodes_accepted_by(await _workspace_config(db, project_id))


async def platform_turn_capture_enabled(db: AsyncSession, project_id: str) -> bool:
    return platform_turn_capture_by(await _workspace_config(db, project_id))


async def platform_turn_capture_stored(db: AsyncSession, project_id: str) -> bool:
    """The stored sub-setting as is (for the settings view), independent of the main switch."""
    return _policy_of(await _workspace_config(db, project_id)).get(CAPTURE_PLATFORM_TURNS) is True


async def set_episode_policy(
    db: AsyncSession,
    project_id: str,
    *,
    accepted: bool | None = None,
    capture_platform_turns: bool | None = None,
    actor_id: str | None = None,
) -> None:
    """Store the given switches on the Workspace row; ``None`` leaves one as is. Flushes; the caller commits.

    With ``actor_id``, a change is audited as ``knowledge.episode_policy.update``: the switch keys with
    their old and new booleans only, never any other text.
    """
    project = await db.get(Project, project_id)
    if project is None:
        return
    config = dict(project.config or {})
    policy = dict(_policy_of(config))
    requested = {ACCEPT_SESSION_EPISODES: accepted, CAPTURE_PLATFORM_TURNS: capture_platform_turns}
    changes: dict[str, dict[str, bool]] = {}
    for key, value in requested.items():
        if value is None:
            continue
        old = policy.get(key) is True
        policy[key] = bool(value)
        if old != bool(value):
            changes[key] = {"old": old, "new": bool(value)}
    config[EPISODE_POLICY_KEY] = policy
    project.config = config
    flag_modified(project, "config")
    if actor_id is not None and changes:
        db.add(
            AuditLog(
                user_id=actor_id,
                action=POLICY_AUDIT_ACTION,
                resource_type="workspace",
                resource_id=project_id,
                details={"workspace_id": project_id, "changes": changes},
            )
        )
    await db.flush()


async def set_episodes_accepted(db: AsyncSession, project_id: str, *, accepted: bool) -> None:
    """Store the main switch on the Workspace row. Flushes; the caller commits."""
    await set_episode_policy(db, project_id, accepted=accepted)


def public_origin(raw: object = None) -> str | None:
    """The configured origin if it is exactly ``scheme://host[:port]``; otherwise ``None``."""
    value = str(get_settings().platform_public_origin if raw is None else raw or "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def session_link(origin: str, session_id: str) -> str:
    return f"{origin}/chat?session_id={session_id}"


__all__ = [
    "ACCEPT_SESSION_EPISODES",
    "CAPTURE_PLATFORM_TURNS",
    "EPISODE_POLICY_KEY",
    "EPISODE_WRITER_ROLES",
    "POLICY_AUDIT_ACTION",
    "episodes_accepted",
    "episodes_accepted_by",
    "platform_turn_capture_by",
    "platform_turn_capture_enabled",
    "platform_turn_capture_stored",
    "public_origin",
    "session_link",
    "set_episode_policy",
    "set_episodes_accepted",
]
