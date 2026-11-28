"""Delivery rules of every run-bound shell command: no push on the device, no SCM / Jira client or host."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.command_match import command_segments, git_normalized, segment_matches
from ...agent_gateway.tool_check import ToolDecision
from ..run_texts import run_text
from .hard_deny import hard_denied
from .tool_denial import REASON_HARD_DENY, REASON_PUSH_BY_PLATFORM, REASON_SCM_CLIENT, _deny

SCM_CLIENTS = frozenset({"gh", "glab", "hub", "jira", "acli", "bb"})
HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh", "httpie"})
DEFAULT_SCM_HOSTS = frozenset({"github.com", "api.github.com", "gitlab.com", "bitbucket.org", "api.bitbucket.org",
                               "atlassian.net", "atlassian.com"})


async def scm_hosts(db: AsyncSession, workspace_id: str | None) -> frozenset[str]:
    from ....models import BuiltInToolConfig

    rows = (await db.execute(select(BuiltInToolConfig.config).where(
        BuiltInToolConfig.tool_name.in_(("jira", "github", "gitlab", "bitbucket")),
        or_(BuiltInToolConfig.project_id.is_(None), BuiltInToolConfig.project_id == workspace_id),
    ))).scalars().all()
    hosts = set(DEFAULT_SCM_HOSTS)
    for config in rows:
        for value in dict(config or {}).values():
            host = urlparse(str(value)).hostname if isinstance(value, str) and "://" in value else None
            if host:
                hosts.add(host.lower())
    return frozenset(hosts)


def _host_matches(argument: str, hosts: frozenset[str]) -> bool:
    candidate = argument if "://" in argument else f"https://{argument}"
    host = (urlparse(candidate).hostname or "").lower()
    return bool(host) and any(host == item or host.endswith("." + item) for item in hosts)


def _bash_run_rules(command: str, *, hosts: frozenset[str]) -> ToolDecision | None:
    if (why := hard_denied(command)) is not None:
        return _deny(REASON_HARD_DENY, run_text("block.hard_deny", reason_text=why))
    segments = command_segments(command)
    if segments is None:
        # A command the parser cannot read stays strict for delivery: its words decide the SCM-client
        # and push rules instead of no segments at all.
        segments = _words_as_segment(command)
    for segment in segments:
        name = posixpath.basename(segment[0]) if segment else ""
        if name in SCM_CLIENTS or (name in HTTP_CLIENTS and any(_host_matches(arg, hosts) for arg in segment[1:])):
            return _deny(REASON_SCM_CLIENT, run_text("block.scm_client"))
        if segment_matches(segment, ("git", "push")) or git_normalized(segment)[1:2] == ("send-pack",):
            return _deny(REASON_PUSH_BY_PLATFORM, run_text("block.push"))
    return None


_WORD = re.compile(r"[A-Za-z0-9_.:/@-]+")


def _words_as_segment(command: str) -> list[tuple[str, ...]]:
    words = _WORD.findall(str(command or ""))
    segments: list[tuple[str, ...]] = []
    for index, word in enumerate(words):
        name = posixpath.basename(word)
        if name in SCM_CLIENTS or name in HTTP_CLIENTS:
            segments.append((name, *words[index + 1:]))
        elif name == "git" and any(item in ("push", "send-pack") for item in words[index + 1:]):
            segments.append(("git", "push"))
    return segments
