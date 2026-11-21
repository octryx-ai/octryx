"""How a read-only command may be invoked: by its plain name, with the caller's own environment.

One rule for every read-only path that judges a shell command string (the platform's read-only command
rule and the agent gateway's read-only Bash check). The read-only rules classify a command by its
name; anything that changes what that name runs or how it is configured would make that
classification wrong, so on a read-only path a segment is refused when it

- starts with an environment assignment (``HOME=/x``, ``PATH=/x``, ``KUBECONFIG=/x``: another config
  file, another binary on the path, another kubeconfig),
- starts with a wrapper that runs another command (``env``, ``command``, ``exec``, ``nice``,
  ``timeout``, ``sudo``, a shell, ``xargs`` …) followed by anything,
- names its program by a path (``/tmp/x/kubectl``, ``./kubectl``): the name no longer says which binary, or
- uses an option of an admitted read command that writes or executes (``find -delete``, ``sort -o``,
  ``sed 'w f'`` …; ``read_only_options``).

Allowed: a plain program name, no prefix, reading options only. Unknown programs (also unknown
wrappers such as ``firejail``) are refused by the command rules, which admit listed programs only.

Before any of that, the original string is checked for shell expansion (``shell_expansion``): globs,
braces, ``$`` expansions, ANSI-C quoting, tilde, history and comments are refused unless quoted
literally, because bash would run other words than the ones judged here. The segments are the raw ones
(``agent_gateway.command_match.raw_command_segments``), before the normalization that drops
assignments and wrappers. This rule makes the judged words equal to the words bash runs; it is not a
shell sandbox.
"""

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
    """Why one raw segment is not a plain invocation (``None`` when it is)."""
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
    """The first reason any segment of a shell command string is not a plain invocation.

    The ORIGINAL text is checked first for shell expansion (``shell_expansion``): the segments below are
    tokenized words, which bash may expand into other words before it runs them.
    """
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
