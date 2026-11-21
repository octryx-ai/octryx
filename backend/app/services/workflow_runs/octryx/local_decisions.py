"""Tool decisions on the device for one phase (``config.tool_decisions: "local"``, opt-in per node).

epic-delivery's story session is plain Claude Code in one session per epic, and its permission
decisions are made in the launcher: the hard-deny list only, no server round trip per tool call. Measured on a
local story run: the PreToolUse round trip took a median 0.8 s per tool call against 0.0 s in plain
Claude Code; 824 s of tool time against 358 s, about 8 minutes per story.

A flagged phase's job offer carries ``local_decisions``, the data the launcher's rules need that only the platform
has (``octryx_claude.local_decisions`` holds the rules, a copy of ``shell_rules.hard_denied``, ``tool_policy``'s push,
SCM and browser rules and ``self_protection``; ``tests/test_epic_delivery.py`` keeps the copy equal):

- ``scm_hosts``: the Workspace's SCM and Jira hosts (an HTTP client aimed at one is refused);
- ``deny_patterns``: the Workspace's command safety ``always_deny_patterns`` (destructive commands);
- ``server_commands``: the command prefixes the Workspace's command rules name (``["git", "push"]``,
  ``["kubectl"]``) and the first words of the person's work-role command rules (``["*"]`` when one starts with a
  wildcard): a command with such a segment still goes to the server, which applies the rule;
- ``server_path_globs``: the Workspace's path rules' globs: a file tool on such a path still goes to the server.

No local decisions (``None``) while the Cedar policy engine enforces: the launcher cannot evaluate published Cedar
policies, so every call keeps the round trip. The launcher also asks the server for everything it cannot decide (a
path outside the repository, an unparseable command, the platform's MCP tools, a run that is not running at the
phase). What the server recorded per call it still records, from the launcher's batches (``sessions/tool-audit``).
"""

from __future__ import annotations

import posixpath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

LOCAL_KEY = "tool_decisions"
LOCAL = "local"
ANY_COMMAND = "*"


def node_decides_locally(node: Any) -> bool:
    """Whether a phase node opted in (``config.tool_decisions`` is exactly ``"local"``)."""
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(LOCAL_KEY) == LOCAL


def _first_word(pattern: str) -> tuple[str, ...]:
    words = str(pattern or "").split()
    if not words or any(char in words[0] for char in "*?["):
        return (ANY_COMMAND,)
    return (posixpath.basename(words[0]),)


def offer_data(policy: Any, exec_config: dict[str, Any], hosts: frozenset[str]) -> dict[str, Any]:
    """The ``local_decisions`` block of a job offer (pure)."""
    from app.services.agent_gateway.policy_keys import RULE_PATH_DENIED

    from ...agent_gateway.tool_check import COMMAND_RULE_KINDS
    from ...work_role_model.commands import ALLOW_KEY, DENY_KEY

    rules = tuple(getattr(policy, "tool_rules", ()) or ())
    commands = {(posixpath.basename(rule.tokens[0]), *rule.tokens[1:]) for rule in rules
                if rule.kind in COMMAND_RULE_KINDS and rule.tokens}
    commands |= {_first_word(pattern) for key in (ALLOW_KEY, DENY_KEY) for pattern in exec_config.get(key) or []}
    return {
        "scm_hosts": sorted(hosts),
        "deny_patterns": [str(item) for item in exec_config.get("always_deny_patterns") or []],
        "server_commands": [list(prefix) for prefix in sorted(commands)],
        "server_path_globs": [rule.glob for rule in rules if rule.kind == RULE_PATH_DENIED and rule.glob],
    }


async def local_decisions_offer(db: AsyncSession, run: WorkflowRun | None, phase: Any,
                                owner_user_id: str | None) -> dict[str, Any] | None:
    """The offer's ``local_decisions`` for a turn of ``run`` working ``phase``; ``None`` when the platform decides."""
    if run is None or not node_decides_locally(phase):
        return None
    from ...agent_gateway.policy import load_workspace_policy
    from ...exec_policy import get_effective_exec_policy_config
    from ...policy_engine.runtime import MODE_ENFORCE, current_runtime, maintain_policy_runtime
    from ...work_role_model.commands import with_role_commands
    from ...work_role_model.effective import effective_permission
    from .scm_rules import scm_hosts

    await maintain_policy_runtime()
    if current_runtime().mode == MODE_ENFORCE:
        return None
    loaded = await load_workspace_policy(db, run.project_id)
    if loaded.policy is None:
        return None
    exec_config = await get_effective_exec_policy_config(db, project_id=run.project_id)
    if owner_user_id:
        exec_config = with_role_commands(exec_config, await effective_permission(db, owner_user_id, run.project_id))
    return offer_data(loaded.policy, exec_config, await scm_hosts(db, run.project_id))


__all__ = ["LOCAL", "LOCAL_KEY", "local_decisions_offer", "node_decides_locally", "offer_data"]
