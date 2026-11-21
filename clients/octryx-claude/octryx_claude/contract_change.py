"""The working copy's change against the run's base commit (``run_contract.facts`` at Stop): a binary patch with
untracked files (a temporary index), or ``base_unavailable`` with the failed git step. git runs without anything the
working copy configures (no hooks, fsmonitor, external diff or textconv)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import os_junk

# The server takes the same (facts.MAX_PATCH); a guard, never a cut of a real story (a story's 447
# screenshot baselines made a 36 MB binary patch, which the old 6 MB bound cut).
MAX_PATCH = 64_000_000
MAX_LINE = 600
GIT_TIMEOUT = 10
# The change itself (read-tree, add -A, diff --binary): a story with hundreds of screenshot baselines makes a
# 40 MB patch, which took longer than GIT_TIMEOUT on a loaded Mac and was reported as a missing base. Three such
# steps stay inside the Stop hook's own timeout (launch.STOP_HOOK_TIMEOUT).
CHANGE_GIT_TIMEOUT = 60
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(value: object, limit: int = MAX_LINE) -> str:
    return _CONTROL.sub(" ", str(value or "")).strip()[:limit]


# git never runs what the working copy configures: the agent could have written its config.
SAFE_GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
            "-c", "diff.external=", "-c", "core.attributesFile=/dev/null")
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _git(root: Path, *args: str, env: dict[str, str] | None = None,
         timeout: float = GIT_TIMEOUT) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run([*SAFE_GIT, *args], cwd=root, capture_output=True, text=True, errors="replace",
                              timeout=timeout, check=False,
                              env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})})
    except (OSError, subprocess.SubprocessError):
        return None


def _git_bytes(root: Path, *args: str, env: dict[str, str] | None = None,
               timeout: float = CHANGE_GIT_TIMEOUT) -> bytes | None:
    """git's output as bytes (a patch carries file contents, which need not be UTF-8); ``None`` when git failed."""
    try:
        done = subprocess.run([*SAFE_GIT, *args], cwd=root, capture_output=True, timeout=timeout, check=False,
                              env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})})
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


_DIFF = ("diff", "--cached", "--binary", "--no-color", "--no-ext-diff", "--no-textconv")


def _not_utf8(root: Path, base: str, env: dict[str, str]) -> list[bytes]:
    """The changed paths whose content (at ``base`` or in the index) is not UTF-8."""
    names = _git_bytes(root, "diff", "--cached", "--name-only", "-z", "--no-renames", base, env=env) or b""
    found = []
    for name in [item for item in names.split(b"\0") if item]:
        path = name.decode("utf-8", "surrogateescape")
        for spec in (f"{base}:{path}", f":{path}"):
            content = _git_bytes(root, "cat-file", "blob", spec, env=env)
            try:
                (content or b"").decode("utf-8")
            except UnicodeDecodeError:
                found.append(name)
                break
    return found


_GLOB = frozenset(b"*?[\\")


def _attribute_line(name: bytes) -> bytes:
    """``"/<path>" -diff`` for git's attributes: the path anchored, its glob characters escaped, C-quoted."""
    pattern = b"/" + b"".join(b"\\" + bytes([c]) if c in _GLOB else bytes([c]) for c in name)
    quoted = b"".join(b"\\" + bytes([c]) if c in b'"\\' else b"\\%03o" % c if c < 32 or c == 127 else bytes([c])
                      for c in pattern)
    return b'"' + quoted + b'" -diff\n'


def _patch(root: Path, base: str, env: dict[str, str]) -> str | None:
    """The binary patch as text. A text file that is not UTF-8 (Latin-1, no NUL byte, so git diffs it as text) goes
    as a binary hunk instead: its bytes stay exact and the patch stays text, and decoding it never raises
    ``UnicodeDecodeError`` (which would end the work-git job without a report)."""
    raw = _git_bytes(root, *_DIFF, base, env=env)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    with tempfile.TemporaryDirectory(prefix="octryx-attributes-") as scratch:
        attributes = Path(scratch) / "attributes"
        attributes.write_bytes(b"".join(_attribute_line(name) for name in _not_utf8(root, base, env)))
        raw = _git_bytes(root, "-c", f"core.attributesFile={attributes}", *_DIFF, base, env=env)
    try:
        return raw.decode("utf-8") if raw is not None else None
    except UnicodeDecodeError:
        return None  # the repository's own .gitattributes forces a text diff of such a file: no patch


CHANGE_ATTEMPTS = 2
CHANGE_RETRY_SECONDS = 1.0
MAX_REASON = 300


def _failed(step: str, done: subprocess.CompletedProcess | None) -> str:
    """``<step>: <git's last words>`` (timed out or not started when there is no result)."""
    if done is None:
        return f"{step}: timed out or could not start git"
    words = " ".join(str(done.stderr or "").split()[-40:])
    return _clean(f"{step}: exit {done.returncode}" + (f": {words}" if words else ""), MAX_REASON)


def _change_once(root: Path, base: str) -> dict[str, Any]:
    known = _git(root, "cat-file", "-e", f"{base}^{{commit}}", timeout=CHANGE_GIT_TIMEOUT)
    if known is None or known.returncode != 0:
        return {"base": base, "base_unavailable": True, "reason": _failed("cat-file", known)}
    with tempfile.TemporaryDirectory(prefix="octryx-facts-") as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}  # the user's own index stays untouched
        for name, step in (("read-tree HEAD", ("read-tree", "HEAD")), ("add -A", os_junk.add_all())):
            done = _git(root, *step, env=env, timeout=CHANGE_GIT_TIMEOUT)
            if done is None or done.returncode != 0:
                return {"base": base, "base_unavailable": True, "reason": _failed(name, done)}
        patch = _patch(root, base, env)
    if patch is None:
        return {"base": base, "base_unavailable": True, "reason": "diff: git failed or the patch is no text"}
    return {"base": base, "patch": patch[:MAX_PATCH], "truncated": len(patch) > MAX_PATCH}


def change(root: Path, base: str) -> dict[str, Any]:
    """The working copy against ``base`` as a binary patch, untracked files included; or why there is none
    (``base_unavailable`` with ``reason``: the git step and its last words).

    A git step can fail transiently (a file written while ``add -A`` reads it); without a change the hands-on step
    takes the change as unreadable and the review has no diff (``review_no_decision``). So a failed step is tried once
    more after a second, and the report says which step failed and why."""
    if not _SHA.match(base or ""):
        return {"base": base, "base_unavailable": True, "reason": "no base commit in the run contract"}
    result: dict[str, Any] = {}
    for attempt in range(CHANGE_ATTEMPTS):
        if attempt:
            time.sleep(CHANGE_RETRY_SECONDS)
        result = _change_once(root, base)
        if not result.get("base_unavailable"):
            return {**result, **({"attempts": attempt + 1} if attempt else {})}
    return {**result, "attempts": CHANGE_ATTEMPTS}
