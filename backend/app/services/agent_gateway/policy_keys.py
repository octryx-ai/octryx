"""The fixed keys, limits and baseline of the Workspace's ``agent_gateway_policy`` (see ``policy.py``)."""

from __future__ import annotations

from typing import Any

from ..devices.device_runs_keys import DEVICE_RUNS_KEY
from .engine_keys import ENGINES_KEY
from .handoff_policy_keys import HANDOFF_POLICY_KEY
from .review_keys import REVIEW_KEY
from .seat_policy_keys import SEAT_POLICY_KEYS
from .transcript_policy_keys import SESSION_TRANSCRIPTS_KEY

AGENT_GATEWAY_POLICY_CONFIG_KEY = "agent_gateway_policy"

POLICY_SOURCE_WORKSPACE = "workspace"
POLICY_SOURCE_BASELINE = "baseline"

RULE_COMMAND_PREFIX_DENIED = "command_prefix_denied"
RULE_COMMAND_REQUIRES_ARGUMENT = "command_requires_argument"
RULE_COMMAND_ARGUMENT_DENIED = "command_argument_denied"
RULE_PATH_DENIED = "path_denied"
RULE_KINDS = frozenset(
    {RULE_COMMAND_PREFIX_DENIED, RULE_COMMAND_REQUIRES_ARGUMENT, RULE_COMMAND_ARGUMENT_DENIED, RULE_PATH_DENIED}
)
_RULE_FIELDS = {
    RULE_COMMAND_PREFIX_DENIED: {"prefix"},
    RULE_COMMAND_REQUIRES_ARGUMENT: {"command", "argument"},
    RULE_COMMAND_ARGUMENT_DENIED: {"command", "argument"},
    RULE_PATH_DENIED: {"tools", "glob"},
}
# A session outside a workflow run follows the person's Claude Code permission mode
# ("follow_permission_mode", the default) or stays read-only in a strict Workspace ("read_only"); bypass mode may be
# switched off per Workspace ("bypass_permissions": "disabled"). The platform's deny rules apply in every mode.
FREE_SESSIONS_KEY = "free_sessions"
FREE_SESSIONS_MODES = frozenset({"follow_permission_mode", "read_only"})
BYPASS_KEY = "bypass_permissions"
BYPASS_MODES = frozenset({"allowed", "disabled"})
# Per Workspace, what each role's sessions may do, set by its admins:
# {"viewer": "read_only", "member": "edit", "owner": "bypass", "admin": "bypass"}.
ROLE_MODES_KEY = "role_modes"
ROLE_MODE_ROLES = frozenset({"viewer", "member", "owner", "admin"})
ROLE_MODE_CEILINGS = frozenset({"read_only", "edit", "bypass"})
_TOP_LEVEL_KEYS = frozenset(
    {"verification", "tool_rules", "client_permissions", "session_budget", "sandbox", HANDOFF_POLICY_KEY,
     DEVICE_RUNS_KEY, FREE_SESSIONS_KEY, BYPASS_KEY, ROLE_MODES_KEY, SESSION_TRANSCRIPTS_KEY, ENGINES_KEY,
     REVIEW_KEY, *SEAT_POLICY_KEYS}
)
_VERIFICATION_KEYS = frozenset({"test_command_prefixes", "change_tools"})
_PERMISSION_KEYS = frozenset({"deny", "ask", "allow"})
# The set the agent needs to work on its own (no permission prompt on the phone for every test
# run or local commit). Tests, Python, reading, the local git workflow up to the commit; never a push (the
# platform pushes), never deleting or the network — those keep asking or stay denied. A Workspace sets its own
# list in client_permissions.allow; without one it gets this set.
AUTONOMY_ALLOW: tuple[str, ...] = (
    "Bash(.venv/bin/python:*)", "Bash(python:*)", "Bash(python3:*)", "Bash(pytest:*)",
    "Bash(ls:*)", "Bash(find:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
    "Bash(grep:*)", "Bash(rg:*)", "Bash(mkdir:*)", "Bash(touch:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)",
    "Bash(git commit:*)", "Bash(git checkout:*)", "Bash(git switch:*)", "Bash(git branch:*)",
    "Bash(git restore:*)", "Bash(git stash:*)",
    "TodoWrite",
)
_BUDGET_KEYS = frozenset({"per_user_daily_usd"})
# octryx-claude sessions spend at most this much per user and UTC day. A Workspace that stored its own value keeps it.
BASELINE_DAILY_BUDGET_USD = 200
MAX_DAILY_BUDGET_USD = 100_000

MAX_RULES = 100
MAX_TOKENS = 16
MAX_TOKEN_CHARS = 200
MAX_LIST_ITEMS = 200
MAX_TEXT_CHARS = 300
MAX_RULE_ID_CHARS = 80

BASELINE_POLICY: dict[str, Any] = {
    "tool_rules": [
        {
            "id": "kubectl-requires-context",
            "kind": RULE_COMMAND_REQUIRES_ARGUMENT,
            "command": ["kubectl"],
            "argument": "--context",
        },
        {"id": "no-push-to-main", "kind": RULE_COMMAND_PREFIX_DENIED, "prefix": ["git", "push", "origin", "main"]},
        {"id": "no-push-to-master", "kind": RULE_COMMAND_PREFIX_DENIED, "prefix": ["git", "push", "origin", "master"]},
        {
            "id": "no-force-push",
            "kind": RULE_COMMAND_ARGUMENT_DENIED,
            "command": ["git", "push"],
            "argument": "--force",
        },
        {
            "id": "no-force-push-short",
            "kind": RULE_COMMAND_ARGUMENT_DENIED,
            "command": ["git", "push"],
            "argument": "-f",
        },
        {
            "id": "no-env-files",
            "kind": RULE_PATH_DENIED,
            "tools": ["Read", "Edit", "Write", "MultiEdit"],
            "glob": "**/.env",
        },
        {
            "id": "no-aws-credentials",
            "kind": RULE_PATH_DENIED,
            "tools": ["Read", "Edit", "Write", "MultiEdit"],
            "glob": "**/.aws/**",
        },
        {
            "id": "no-aws-credentials-home",
            "kind": RULE_PATH_DENIED,
            "tools": ["Read", "Edit", "Write", "MultiEdit"],
            "glob": "~/.aws/**",
        },
    ],
    "client_permissions": {
        "deny": [
            "Bash(git push origin main:*)",
            "Bash(git push origin master:*)",
            "Bash(git push --force:*)",
            "Read(./.env)",
            "Read(~/.aws/**)",
        ],
        "ask": [],
        "allow": list(AUTONOMY_ALLOW),
    },
    "session_budget": {"per_user_daily_usd": BASELINE_DAILY_BUDGET_USD},
}


class AgentGatewayPolicyError(ValueError):
    """A policy that does not validate; ``reason`` is a fixed code, ``path`` names the field."""

    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path
