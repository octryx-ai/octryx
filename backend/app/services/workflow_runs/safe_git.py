"""git on a working copy an agent writes, without running anything that working copy configures."""

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


def git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    from ..execution_runtime.server_env import with_git_hardening

    # The command-line configuration of ``server_env`` too: it wins over a planted ``.git/config``.
    return with_git_hardening({**(os.environ if base is None else base), "GIT_CONFIG_NOSYSTEM": "1",
                               "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})


async def git(cwd: Path | str, *args: str, stdin: bytes | None = None,
              env: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    # Credentials travel in env (GIT_CONFIG_* or askpass), never in argv or a URL.
    try:
        process = await asyncio.create_subprocess_exec(
            "git", *SAFE_CONFIG, *IDENTITY, *args, cwd=str(cwd), env=git_env(env),
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout=TIMEOUT)
    except (OSError, TimeoutError):
        return 1, "", "git_unavailable"
    return int(process.returncode or 0), stdout.decode(errors="replace"), stderr.decode(errors="replace")


@cache
def os_junk_excludes() -> tuple[str, ...]:
    # The launcher's list, so the device's tree and the platform's leave out the same files.
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
    if (await git(cwd, "add", "-A", "--", ".", *os_junk_excludes()))[0] != 0:
        return ""
    code, out, _err = await git(cwd, "write-tree")
    return out.strip() if code == 0 else ""


async def staged_change(cwd: Path | str, base: str) -> tuple[str, str]:
    tree = await staged_tree(cwd)
    if not tree:
        return "", ""
    code, diff, _err = await git(cwd, *DIFF, "--cached", base or "HEAD")
    return (diff, tree) if code == 0 else ("", "")


async def tree_of(cwd: Path | str, ref: str) -> str:
    code, out, _err = await git(cwd, "rev-parse", f"{ref}^{{tree}}")
    return out.strip() if code == 0 else ""


async def patch_tree(cwd: Path | str, base: str, patch: str) -> str:
    # A throwaway index: the working copy and its index stay untouched.
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
    if (await git(cwd, "reset", "-q", "--hard", base))[0] != 0:
        return f"the working copy has no commit {base[:12]}"
    await git(cwd, "clean", "-fdq")
    code, _out, err = await git(cwd, "apply", "--index", "--binary", "--whitespace=nowarn", "-",
                                stdin=patch.encode())
    return "" if code == 0 else (err.strip().splitlines() or ["the patch does not apply"])[-1][:300]


__all__ = ["DIFF", "SAFE_CONFIG", "apply_patch", "git", "git_env", "patch_tree", "staged_change", "staged_tree",
           "tree_of"]
