"""The sandbox network a Workspace allows its governed Claude Code sessions.

``agent_gateway_policy.sandbox.allowed_domains`` is the list of domains that Bash inside Claude
Code's OS sandbox may reach, for builds and package registries (``pypi.org``,
``*.npmjs.org``). It is Workspace data, edited by an admin or owner and validated here. It is not
a code default: the baseline is an empty list, which means Claude Code asks the user per domain.

The client policy hands the list to the launcher, which writes it into the sandbox settings
(``network.allowedDomains``). The platform host itself is never allowed: the launcher keeps it in
``deniedDomains``, and a Workspace entry naming it is refused here when the platform's public
origin is known.

An entry is a host name in lower case, optionally with one leading ``*.`` wildcard. It has no
scheme, port, path or credentials, and is at most 253 characters. At most :data:`MAX_DOMAINS`
entries are allowed.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

MAX_DOMAINS = 200
MAX_DOMAIN_CHARS = 253
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"^(?:\*\.)?{_LABEL}(?:\.{_LABEL})+$")
SANDBOX_KEYS = frozenset({"allowed_domains"})


class SandboxPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def _platform_host() -> str | None:
    from ..knowledge.episodes.policy import public_origin

    origin = public_origin()
    return (urlsplit(origin).hostname or "").lower() if origin else None


def normalize_sandbox(value: Any, path: str) -> dict[str, Any]:
    """The validated ``sandbox`` section; raises :class:`SandboxPolicyError` with a fixed reason."""
    if not isinstance(value, dict):
        raise SandboxPolicyError("not_an_object", path)
    unknown = set(value) - SANDBOX_KEYS
    if unknown:
        raise SandboxPolicyError("unknown_field", f"{path}.{sorted(unknown)[0]}")
    domains = value.get("allowed_domains", [])
    if not isinstance(domains, list) or len(domains) > MAX_DOMAINS:
        raise SandboxPolicyError("invalid_list", f"{path}.allowed_domains")
    platform = _platform_host()
    normalized: list[str] = []
    for index, raw in enumerate(domains):
        entry = raw.strip().lower() if isinstance(raw, str) else ""
        if not entry or len(entry) > MAX_DOMAIN_CHARS or not _DOMAIN.fullmatch(entry):
            raise SandboxPolicyError("invalid_domain", f"{path}.allowed_domains[{index}]")
        if platform and entry.removeprefix("*.") == platform:
            raise SandboxPolicyError("platform_host_not_allowed", f"{path}.allowed_domains[{index}]")
        if entry not in normalized:
            normalized.append(entry)
    return {"allowed_domains": normalized}


async def workspace_sandbox_domains(db: Any, project_id: str) -> tuple[str, ...] | None:
    """The Workspace's allowed sandbox domains; ``None`` when its stored policy no longer validates."""
    from .policy import load_workspace_policy

    loaded = await load_workspace_policy(db, project_id)
    return loaded.policy.sandbox_allowed_domains if loaded.policy is not None else None


async def set_workspace_sandbox_domains(db: Any, *, project_id: str, domains: Any, actor_user_id: str) -> None:
    """Store the allowed domains through the one project-config write path (validated, audited).

    A Workspace still on the baseline policy keeps the baseline rules: the stored policy starts from
    a copy of the baseline, so setting domains never drops the code-defined deny rules.
    """
    import copy

    from sqlalchemy import select

    from ...models import Project
    from ..admin.project.admin_project_config_service import merge_project_config
    from .policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, BASELINE_POLICY

    config = (await db.execute(select(Project.config).where(Project.id == project_id))).scalar_one_or_none()
    stored = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    base = dict(stored) if isinstance(stored, dict) and stored else copy.deepcopy(BASELINE_POLICY)
    base["sandbox"] = {"allowed_domains": domains}
    await merge_project_config(
        db, project_id=project_id, patch={AGENT_GATEWAY_POLICY_CONFIG_KEY: base}, actor_user_id=actor_user_id
    )


__all__ = [
    "MAX_DOMAINS",
    "SandboxPolicyError",
    "normalize_sandbox",
    "set_workspace_sandbox_domains",
    "workspace_sandbox_domains",
]
