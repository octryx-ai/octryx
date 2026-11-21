"""git on a working copy an agent writes, without running anything that working copy configures (review fix).

The platform runs git in working copies its agents change (the run's own, a slice's worktree), so every call ignores
the repository's executable configuration: no hooks, no fsmonitor, no external diff or textconv driver, no pager,
no system configuration; diffs are always text, so a ``-diff`` attribute hides no change from the reviewer. A run's
phases never write ``.git/`` or ``.gitattributes`` (``protected_paths``). Commits use a fixed platform identity.

The change of a working copy is its **tree** (``git add -A`` + ``git write-tree``): what the reviewer reviewed and
what the platform pushes are compared by that hash (``platform/scm.push``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from functools import cache
from pathlib import Path

SAFE_CONFIG = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
               "-c", "diff.external=", "-c", "core.attributesFile=/dev/null", "-c", "commit.gpgsign=false")
IDENTITY = ("-c", "user.name=Octryx workflow run", "-c", "user.email=workflow-run@octryx.invalid")
DIFF = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "--text")
TIMEOUT = 120

logger = logging.getLogger(__name__)


def _env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    from ..execution_runtime.server_env import with_git_hardening

    # The command-line configuration of ``server_env`` too: it wins over a planted ``.git/config``.
    return with_git_hardening({**(os.environ if base is None else base), "GIT_CONFIG_NOSYSTEM": "1",
                               "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})


async def git(cwd: Path | str, *args: str, stdin: bytes | None = None,
              env: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)``; an unavailable git or a timeout is exit code 1.

    ``env``: the whole environment of a command that talks to the remote (the connection's Git
    auth, ``workspace/origin_auth.py``, which carries the credential as ``GIT_CONFIG_*`` or an askpass, never in
    argv or a URL); ``None`` is this process's environment."""
    try:
        process = await asyncio.create_subprocess_exec(
            "git", *SAFE_CONFIG, *IDENTITY, *args, cwd=str(cwd), env=_env(env),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=TIMEOUT)
    except (OSError, TimeoutError):
        return 1, "", "git_unavailable"
    return int(process.returncode or 0), stdout.decode(errors="replace"), stderr.decode(errors="replace")


@cache
def os_junk_excludes() -> tuple[str, ...]:
    """Pathspec excludes for the operating system's own files (``.DS_Store``, ``Thumbs.db``, ...): the launcher's list
    (``octryx_claude/os_junk.json``, shipped with the image), so the device's tree and the platform's leave out the
    same files. Without it nothing is left out, and the log says so."""
    from ..octryx_client.artifact import default_client_dir  # noqa: PLC0415

    path = default_client_dir() / "octryx_claude" / "os_junk.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files, folders = list(data["files"]), list(data["folders"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("os_junk_list_unavailable path=%s", path)
        return ()
    return (*(f":(exclude,glob)**/{name}" for name in files),
            *(f":(exclude,glob)**/{name}/**" for name in folders))


async def staged_tree(cwd: Path | str) -> str:
    """The working copy's whole change staged, as its tree hash ('' when git failed); the operating system's own
    files stay out, as on the device (otherwise Finder's ``.DS_Store`` made the trees differ)."""
    if (await git(cwd, "add", "-A", "--", ".", *os_junk_excludes()))[0] != 0:
        return ""
    code, out, _err = await git(cwd, "write-tree")
    return out.strip() if code == 0 else ""


async def staged_change(cwd: Path | str, base: str) -> tuple[str, str]:
    """``(diff against base, tree)`` of the working copy including new files; ``("", "")`` when git failed."""
    tree = await staged_tree(cwd)
    if not tree:
        return "", ""
    code, diff, _err = await git(cwd, *DIFF, "--cached", base or "HEAD")
    return (diff, tree) if code == 0 else ("", "")


async def tree_of(cwd: Path | str, ref: str) -> str:
    code, out, _err = await git(cwd, "rev-parse", f"{ref}^{{tree}}")
    return out.strip() if code == 0 else ""


async def patch_tree(cwd: Path | str, base: str, patch: str) -> str:
    """The tree of ``base`` plus ``patch``, built in a throwaway index (the working copy and its index stay
    untouched, only objects are written); '' when the base is unknown or the patch does not apply."""
    import tempfile

    if not base or not patch.strip():
        return ""
    if (await git(cwd, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"))[0] != 0:
        return ""
    with tempfile.TemporaryDirectory(prefix="octryx-patch-tree-") as folder:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
        if (await git(cwd, "read-tree", base, env=env))[0] != 0:
            return ""
        if (await git(cwd, "apply", "--cached", "--binary", "--whitespace=nowarn", "-", env=env,
                      stdin=patch.encode()))[0] != 0:
            return ""
        code, out, _err = await git(cwd, "write-tree", env=env)
    return out.strip() if code == 0 else ""


async def apply_patch(cwd: Path | str, base: str, patch: str) -> str:
    """Make the working copy exactly ``base`` plus ``patch`` (staged); '' or why it did not apply."""
    if (await git(cwd, "reset", "-q", "--hard", base))[0] != 0:
        return f"the working copy has no commit {base[:12]}"
    await git(cwd, "clean", "-fdq")
    code, _out, err = await git(cwd, "apply", "--index", "--binary", "--whitespace=nowarn", "-",
                                stdin=patch.encode())
    return "" if code == 0 else (err.strip().splitlines() or ["the patch does not apply"])[-1][:300]


__all__ = ["DIFF", "apply_patch", "git", "patch_tree", "staged_change", "staged_tree", "tree_of"]
