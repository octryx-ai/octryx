"""The review bot's opt-in per repository.

A Workspace repository (``CodeRepository``) carries the bot's settings in ``config_json["pr_review_bot"]``, next to
the repository's code style, so no migration is needed and a repository removed from the Workspace takes its
settings with it:

- ``trigger``: ``webhook`` (each pull request event), ``sync`` (the hourly pull request sync), ``both`` or ``off``.
  A repository without settings is ``off``: the bot posts on a repository only after an admin switched it on;
- ``protected_branches``: the branches where Octryx only ever opens pull requests (never pushes), kept per repository
  for the correction runs of a later stage; the bot itself never pushes and never merges;
- ``review_drafts``: draft pull requests are reviewed too (default: not until they are ready for review);
- ``fix_runs``: ``@octryx fix`` / ``write tests`` may push onto pull request branches (default off);
- ``size_limit_lines`` / ``size_limit_files``: the size brake (default 800 / 25 carefully read lines / files);
- ``status_policy``: what the commit status ``octryx-review`` says (the platform
  informs and never silently blocks a team's merge): ``inform`` (default; ``success`` with the findings counted in
  its description, ``failure`` only for a committed secret) or ``gate`` (``failure`` on blocking findings, switched
  on deliberately where a team wants the review as a required check).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.code_intelligence import CodeRepository
from ..workflow_runs.platform.repo_ref import PROVIDERS, SNAPSHOT_PROVIDER, record_path

KEY = "pr_review_bot"
TRIGGER_WEBHOOK, TRIGGER_SYNC, TRIGGER_BOTH, TRIGGER_OFF = "webhook", "sync", "both", "off"
TRIGGERS = (TRIGGER_WEBHOOK, TRIGGER_SYNC, TRIGGER_BOTH, TRIGGER_OFF)
STATUS_INFORM, STATUS_GATE = "inform", "gate"
STATUS_POLICIES = (STATUS_INFORM, STATUS_GATE)
# Providers the bot posts on (GitHub, Bitbucket and GitLab).
BOT_PROVIDERS = ("github", "gitlab", "bitbucket")


class BotSettingsError(ValueError):
    def __init__(self, reason: str, path: str = "") -> None:
        super().__init__(reason)
        self.reason, self.path = reason, path


# Git's own bound of a ref name is far above this; a branch name longer than a line is a pasted mistake.
MAX_BRANCH = 255


def _branch_problem(name: str, seen: set[str]) -> bool:
    """A protected branch the UI must point at: empty, too long, with spaces or ``..``, or listed twice."""
    return not name or len(name) > MAX_BRANCH or any(char.isspace() for char in name) or ".." in name or name in seen


@dataclass(frozen=True, slots=True)
class BotSettings:
    trigger: str = TRIGGER_OFF
    protected_branches: tuple[str, ...] = field(default_factory=tuple)
    review_drafts: bool = False
    #: ``@octryx fix`` / ``write tests`` may push onto this repository's pull request branches (off unless
    #: a Workspace admin switches it on).
    fix_runs: bool = False
    #: The size brake: more carefully read lines or files than this adds a note suggesting a split.
    size_limit_lines: int = 800
    size_limit_files: int = 25
    #: Globs of the repository's own sensitive paths for the hotspots, besides the built-in areas.
    hotspot_paths: tuple[str, ...] = field(default_factory=tuple)
    #: ``inform`` (default) or ``gate``: whether blocking findings fail the commit status (module docstring).
    status_policy: str = STATUS_INFORM

    def on_webhook(self) -> bool:
        return self.trigger in (TRIGGER_WEBHOOK, TRIGGER_BOTH)

    def on_sync(self) -> bool:
        return self.trigger in (TRIGGER_SYNC, TRIGGER_BOTH)

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["protected_branches"] = list(self.protected_branches)
        record["hotspot_paths"] = list(self.hotspot_paths)
        return record


def parse_settings(raw: Any, *, strict: bool = False) -> BotSettings:
    """The stored or submitted settings; ``strict`` (an admin's PUT) refuses what a stored record only ignores."""
    if not isinstance(raw, dict):
        if strict and raw is not None:
            raise BotSettingsError("settings_not_an_object")
        return BotSettings()
    trigger = str(raw.get("trigger") or TRIGGER_OFF).strip().lower()
    if trigger not in TRIGGERS:
        if strict:
            raise BotSettingsError("trigger_unknown")
        trigger = TRIGGER_OFF
    branches = raw.get("protected_branches") or []
    if not isinstance(branches, list) or not all(isinstance(item, str) for item in branches):
        if strict:
            raise BotSettingsError("protected_branches_not_a_list")
        branches = []
    if strict:
        seen: set[str] = set()
        for index, item in enumerate(branches):
            if _branch_problem(item.strip(), seen):
                raise BotSettingsError("protected_branch_invalid", f"protected_branches[{index}]")
            seen.add(item.strip())
    unique = tuple(dict.fromkeys(item.strip() for item in branches if item.strip()))
    limits = []
    for name, default in (("size_limit_lines", 800), ("size_limit_files", 25)):
        value = raw.get(name, default)
        if type(value) is not int or not 1 <= value <= 100_000:
            if strict and name in raw:
                raise BotSettingsError("size_limit_invalid", name)
            value = default
        limits.append(value)
    globs = raw.get("hotspot_paths") or []
    if not isinstance(globs, list) or len(globs) > 50 or not all(
            isinstance(item, str) and 0 < len(item.strip()) <= 200 for item in globs):
        if strict and "hotspot_paths" in raw:
            raise BotSettingsError("hotspot_paths_invalid", "hotspot_paths")
        globs = []
    policy = str(raw.get("status_policy") or STATUS_INFORM).strip().lower()
    if policy not in STATUS_POLICIES:
        if strict:
            raise BotSettingsError("status_policy_unknown", "status_policy")
        policy = STATUS_INFORM
    return BotSettings(trigger, unique, bool(raw.get("review_drafts")), raw.get("fix_runs") is True, *limits,
                       tuple(dict.fromkeys(item.strip() for item in globs)), policy)


def settings_of(record: CodeRepository | None) -> BotSettings:
    return parse_settings(dict(record.config_json or {}).get(KEY) if record is not None else None)


def store_settings(record: CodeRepository, settings: BotSettings) -> None:
    record.config_json = {**dict(record.config_json or {}), KEY: settings.to_dict()}


def repository_of(record: CodeRepository) -> str:
    """The record in the run's notation (``github:owner/repo``), ``''`` for a provider the bot does not post on."""
    provider = str(record.provider or "").lower()
    if provider == SNAPSHOT_PROVIDER:
        provider = str(record.name or "").strip("/").partition("/")[0].lower()
    path = record_path(record.name)
    if provider not in BOT_PROVIDERS or provider not in PROVIDERS or "/" not in path:
        return ""
    return f"{provider}:{path}"


async def workspace_repositories(db: AsyncSession, project_id: str) -> list[CodeRepository]:
    return list((await db.execute(select(CodeRepository).where(
        CodeRepository.project_id == project_id, CodeRepository.is_active.is_(True),
    ).order_by(CodeRepository.name))).scalars().all())


async def repository_record(db: AsyncSession, project_id: str, repository: str) -> CodeRepository | None:
    """The Workspace's record of ``repository`` (``<provider>:<path>``, case-insensitive); the provider's own record
    wins over a knowledge snapshot of the same repository."""
    wanted = repository.strip().lower()
    matches = [row for row in await workspace_repositories(db, project_id) if repository_of(row).lower() == wanted]
    return next((row for row in matches if row.provider != SNAPSHOT_PROVIDER), matches[0] if matches else None)


__all__ = ["BOT_PROVIDERS", "KEY", "STATUS_GATE", "STATUS_INFORM", "STATUS_POLICIES",
           "TRIGGERS", "TRIGGER_BOTH", "TRIGGER_OFF", "TRIGGER_SYNC", "TRIGGER_WEBHOOK",
           "BotSettings", "BotSettingsError", "parse_settings", "repository_of", "repository_record", "settings_of",
           "store_settings", "workspace_repositories"]
