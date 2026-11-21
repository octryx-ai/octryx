"""Why a git step against GitHub, GitLab or Bitbucket failed, as a class plus git's last line with secrets removed;
transient failures are retried in the same step.

Without it, the providers kept
only the step's name, so a refused credential, an unreachable service, a rate limit and a full disk looked the same,
and nothing said whether trying again could help. Now every failed step names its class (:data:`CLASSES`) and the
last line git wrote, after redaction (credentialed URLs, tokens); ``network``, ``rate_limit`` and ``server_error``
are tried again with a backoff (:func:`retryable`); ``disk`` is the environment's (the run pauses with that cause).
"""

from __future__ import annotations

import re
from typing import Any

# (class, fixed sentence, status for the run's failure class, stderr markers); first match wins. Credentials before
# network: "unable to access '...': The requested URL returned error: 403" names both.
CLASSES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("disk", "the platform's disk could not be written (full or read-only)", "environment",
     ("no space left", "read-only file system", "disk quota exceeded", "cannot create directory",
      "unable to create temporary file")),
    ("rate_limit", "the service limited the requests (rate limit)", "timeout",
     ("rate limit", "too many requests", "returned error: 429", "secondary rate")),
    ("auth", "the service did not accept the connection's credentials", "denied",
     ("authentication failed", "could not read username", "invalid username or password", "returned error: 401",
      "returned error: 403", "permission denied", "access denied", "not authorized", "unauthorized", "forbidden")),
    ("server_error", "the service answered with a server error", "timeout",
     ("returned error: 500", "returned error: 502", "returned error: 503", "returned error: 504",
      "internal server error", "bad gateway", "service unavailable")),
    ("not_found", "the service does not know the repository or branch", "",
     ("repository not found", "does not exist", "returned error: 404", "not found", "couldn't find remote ref",
      "remote branch") ),
    ("non_fast_forward", "the remote branch has commits the working copy does not have", "",
     ("non-fast-forward", "fetch first", "updates were rejected", "[rejected]", "stale info", "not possible to "
      "fast-forward", "divergent branches")),
    ("declined", "a hook or rule of the service declined it", "",
     ("hook declined", "pre-receive", "protected branch", "branch permission", "[remote rejected]",
      "repository rule violations", "push protection", "gh013", "gh006")),
    ("network", "the service could not be reached (network or timeout)", "timeout",
     ("could not resolve host", "connection timed out", "connection refused", "failed to connect",
      "operation timed out", "timed out", "unable to access", "rpc failed", "early eof", "ssl certificate", "gnutls",
      "connection reset", "network is unreachable", "the remote end hung up", "transfer closed")),
)
RETRYABLE = frozenset({"network", "rate_limit", "server_error"})
NETWORK_COMMANDS = frozenset({"clone", "fetch", "pull", "push", "ls-remote"})
BACKOFF_SECONDS = (2.0, 6.0)  # waits before the second and third try
_SECRET = re.compile(r"(https?://)[^/\s@]+@|\b(gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|"
                     r"glpat-[A-Za-z0-9_-]{8,}|x-token-auth:[^@\s]+)")


def classify(stderr: str, exit_code: int = 1) -> str:
    """The failure's class from git's output; ``network`` for git's own timeout (124), else ``""``."""
    text = str(stderr or "").lower()
    found = next((name for name, _sentence, _status, markers in CLASSES if any(m in text for m in markers)), "")
    return found or ("network" if exit_code == 124 else "")


def retryable(command: list[str], code: int, stderr: str) -> bool:
    """A git network step that failed fast for a reason another try can clear (a step that ran into its own long
    timeout, exit 124, is not tried again)."""
    return (code not in (0, 124) and len(command) > 1 and command[0] == "git" and command[1] in NETWORK_COMMANDS
            and classify(stderr, code) in RETRYABLE)


async def run_with_retry(run_once: Any, command: list[str], **kwargs: Any) -> tuple[int, str, str]:
    """``run_once(command, **kwargs)``, tried again after :data:`BACKOFF_SECONDS` while :func:`retryable`."""
    import asyncio

    result = await run_once(command, **kwargs)
    for wait in BACKOFF_SECONDS:
        if not retryable(command, result[0], result[2]):
            break
        await asyncio.sleep(wait)
        result = await run_once(command, **kwargs)
    return result


_PATH = re.compile(r"(?<![\w:/.])/(?:[\w.~-]+/)*[\w.~-]+")


def last_line(stderr: str) -> str:
    """git's last non-empty line, without credentials, tokens or the platform's own paths, at most 300 characters."""
    lines = [line.strip() for line in str(stderr or "").splitlines() if line.strip()]
    if not lines:
        return ""
    line = _SECRET.sub(lambda match: (match.group(1) or "") + "***" + ("@" if match.group(1) else ""), lines[-1])
    return _PATH.sub("<path>", line)[:300]


def git_failure(error: str, exit_code: int, stderr: str = "", **extra: Any) -> dict[str, Any]:
    """A failed git step: its name, the class and its sentence, git's redacted last line; without output."""
    code = re.sub(r"[^a-z0-9]+", "_", error.lower()).strip("_")
    found = classify(stderr, exit_code)
    if not found:
        return {"error": error, "error_code": code, "exit_code": int(exit_code),
                **({"git_said": last_line(stderr)} if last_line(stderr) else {}), **extra}
    _name, sentence, status, _markers = next(item for item in CLASSES if item[0] == found)
    return {"error": f"{error}: {sentence}", "error_code": code, "error_class": found,
            "exit_code": int(exit_code), **({"status": status} if status else {}),
            **({"git_said": last_line(stderr)} if last_line(stderr) else {}), **extra}


__all__ = ["BACKOFF_SECONDS", "CLASSES", "RETRYABLE", "classify", "git_failure", "last_line", "retryable",
           "run_with_retry"]
