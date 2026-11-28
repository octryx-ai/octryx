"""Tool decisions on the device for one phase (``config.tool_decisions: "local"``, opt-in per node)."""

from __future__ import annotations

import posixpath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

LOCAL_KEY = "tool_decisions"
LOCAL = "local"
ANY_COMMAND = "*"


def node_decides_locally(node: Any) -> bool:
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(LOCAL_KEY) == LOCAL


def _first_word(pattern: str) -> tuple[str, ...]:
    words = str(pattern or "").split()
    if not words or any(char in words[0] for char in "*?["):
        return (ANY_COMMAND,)
    return (posixpath.basename(words[0]),)


def offer_data(policy: Any, exec_config: dict[str, Any], hosts: frozenset[str]) -> dict[str, Any]:
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
