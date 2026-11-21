"""Command safety contract: the checks, list fields, bounds, audit actions and the refusal error."""

from __future__ import annotations

from typing import Any

# The checks in their fixed display order, with the outcomes each can produce.
CHECKS: tuple[dict[str, Any], ...] = (
    {"key": "exec_policy", "label": "Blocked command patterns",
     "description": "Blocks the patterns listed below; in read-only runs only the allowed lists run without asking.",
     "outcomes": ["block", "ask"]},
    {"key": "secret_access", "label": "Secret access",
     "description": "Commands that read secrets (environment dumps, key files, secret stores).", "outcomes": ["ask"]},
    {"key": "command_guardrail", "label": "Content policies on commands",
     "description": "Asks before a command that carries credentials or internal IP addresses (the shipped content "
                    "policies marked for commands).",
     "outcomes": ["ask"]},
    {"key": "llm_risk", "label": "AI risk review", "description": "A model scores the command 0–100.",
     "outcomes": ["ask", "block"]},
)
CHECK_KEYS: tuple[str, ...] = tuple(item["key"] for item in CHECKS)
LIST_FIELDS = {"always_deny_patterns": "always_deny_patterns", "commands": "diagnosis_read_only_commands",
               "git": "diagnosis_git_subcommands", "kubectl": "diagnosis_kubectl_verbs",
               "operators": "shell_risk_operators"}
LLM_KEYS = {"timeout_seconds": "llm_security_analyzer_timeout_seconds",
            "review_threshold": "llm_security_analyzer_review_threshold",
            "deny_threshold": "llm_security_analyzer_deny_threshold"}
LLM_BOUNDS = {"timeout_seconds": (1, 60), "review_threshold": (0, 100), "deny_threshold": (0, 100)}
OVERRIDE_ROW_NAME = "Command safety (Workspace override)"
MAX_ITEMS = 200
MAX_ITEM_CHARS = 300
AUDIT_ACTION = "admin.command_safety.updated"
AUDIT_WORKSPACE_ACTION = "admin.command_safety.workspace_updated"

ERROR_INVALID = "command_safety_invalid"
ERROR_NO_CHECK = "command_safety_no_check"
ERROR_THRESHOLDS = "command_safety_deny_below_review"


class CommandSafetyError(ValueError):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path
