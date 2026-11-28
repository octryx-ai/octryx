"""How a read-only command may be invoked: by its plain name, with the caller's own environment."""

from __future__ import annotations

from collections.abc import Sequence

from ..agent_gateway.command_match import is_env_assignment, raw_command_segments
from .read_only_options import read_option_refusal
from .shell_expansion import shell_expansion_refusal

INVOCATION_ENVIRONMENT = "environment_assignment"
INVOCATION_WRAPPER = "wrapper"
INVOCATION_PATH = "path_qualified_program"
INVOCATION_UNPARSEABLE = "unparseable"

READ_ONLY_REFUSED_WRAPPERS: frozenset[str] = frozenset({
    ".", "bash", "builtin", "busybox", "chroot", "chrt", "command", "dash", "doas", "env", "eval", "exec",
    "flock", "ionice", "ltrace", "nice", "nohup", "nsenter", "runuser", "script", "setsid", "sh", "source",
    "stdbuf", "strace", "su", "sudo", "taskset", "time", "timeout", "unbuffer", "unshare", "watch", "xargs",
    "zsh",
})


def segment_invocation_refusal(segment: Sequence[str]) -> str | None:
    if not segment:
        return None
    program = str(segment[0])
    if is_env_assignment(program):
        return INVOCATION_ENVIRONMENT
    if program in READ_ONLY_REFUSED_WRAPPERS and len(segment) > 1:
        return INVOCATION_WRAPPER
    if "/" in program:
        return INVOCATION_PATH
    # The allowed read commands are bound to their reading options (``read_only_options``).
    return read_option_refusal(segment)


def read_only_invocation_refusal(command: str) -> str | None:
    expansion = shell_expansion_refusal(command)
    if expansion is not None:
        return expansion
    segments = raw_command_segments(command)
    if segments is None:
        return INVOCATION_UNPARSEABLE
    for segment in segments:
        reason = segment_invocation_refusal(segment)
        if reason is not None:
            return reason
    return None


__all__ = [
    "INVOCATION_ENVIRONMENT",
    "INVOCATION_PATH",
    "INVOCATION_UNPARSEABLE",
    "INVOCATION_WRAPPER",
    "READ_ONLY_REFUSED_WRAPPERS",
    "read_only_invocation_refusal",
    "segment_invocation_refusal",
]
