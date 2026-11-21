"""Fixed refusals of the Memory lobe.

Each refusal is one reason from a closed set, mapped to an explicit product state and a fixed
message, so the tool and the HTTP surface say the same thing and no stored text, statement or
dependency message is ever rendered.
"""

from __future__ import annotations

REFUSALS: dict[str, tuple[str, str]] = {
    "invalid_text": (
        "invalid_request",
        "The memory text was empty, too long, or contained invisible control characters.",
    ),
    "invalid_request": ("invalid_request", "The memory request was outside the supported values."),
    "secret_detected": (
        "denied",
        "Memory never stores credentials or secrets; restate it without the secret value.",
    ),
    "author_required": (
        "denied",
        "Workspace memory needs the Workspace admin or owner role; personal memory is always allowed.",
    ),
    "human_turn_required": (
        "denied",
        "Only the user-facing agent may record what the user stated; sub-agents cannot.",
    ),
    "workspace_required": (
        "needs_configuration",
        "Answer feedback is kept in a Workspace's memory; this chat belongs to no Workspace.",
    ),
    "workspace_not_accessible": ("not_found", "The Workspace of this chat is not accessible to you."),
    "not_found": ("not_found", "Memory item not found."),
    "not_active": (
        "invalid_request",
        "This memory item is no longer active (superseded, expired, contradicted or forgotten).",
    ),
}


class MemoryRefusedError(Exception):
    """A memory request refused for one fixed ``reason``."""

    def __init__(self, reason: str) -> None:
        if reason not in REFUSALS:
            reason = "invalid_request"
        self.reason = reason
        super().__init__(reason)

    @property
    def state(self) -> str:
        return REFUSALS[self.reason][0]

    @property
    def message(self) -> str:
        return REFUSALS[self.reason][1]


__all__ = ["REFUSALS", "MemoryRefusedError"]
