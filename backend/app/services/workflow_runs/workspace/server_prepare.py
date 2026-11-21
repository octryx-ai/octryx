"""Prepare a server working copy for the run (the server runtime of ``workspace.prepare``).

The same steps and the same report as a launcher's (``octryx_claude.workspace_prep``), on the folder the server's own
agent works in (the run's working copy, else its chat session's workspace):

1. **branch**: already on the run's branch → kept (its uncommitted changes are that branch's work); another branch with
   uncommitted changes to tracked files → ``dirty`` (never stashed, reset or overwritten: a person decides); else
   ``git fetch origin <branch>`` and check it out (the local branch if it exists, fast-forwarded when it is behind,
   else created tracking ``origin/<branch>``);
2. **environment**: the probes (``spec.probes``) with the declared ``path`` first on ``PATH``; when one fails and a
   setup is declared, the setup runs in the folder (``/bin/sh -c``, ``PIP_REQUIRE_VIRTUALENV=1``, bounded) and the
   probes run again. The ``path`` directories and the declared test command's JUnit report are excluded locally
   (``.git/info/exclude``, ``spec.local_excludes``): a virtual environment or a test report never enters the
   reviewed or pushed change.

Every command, its exit code and the tail of its output are in the report.

**Credential**. The fetches from ``origin`` (the run's branch, its work in progress, the empty check
below) run with ``git_env``: the Bitbucket connection's Git auth environment for the run's repository
(``origin_auth.origin_git_env``, the same as the Bitbucket tools'), so a private Data Center repository is fetched.
The credential is in that environment only (``GIT_CONFIG_*`` or askpass), never in argv, a URL or a file.

**Empty repository**. A clone of a repository without
any commit has an unborn ``HEAD`` and nothing to fetch. When ``origin`` answers ``ls-remote`` with no ref at all, the
folder is put on the run's branch, still unborn (``git symbolic-ref``), and the branch state is ``empty_repository``:
prepared, the agent's first commit creates the branch. A working copy without a commit whose ``origin`` does have refs
is prepared as any other; one whose ``origin`` cannot be read is ``unavailable``.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..safe_git import git
from .spec import refused_command

# Branch states of a folder that is ready for the run (the launcher reports the first two as well).
STATE_ALREADY = "already"
STATE_CHECKED_OUT = "checked_out"
STATE_EMPTY_REPOSITORY = "empty_repository"
READY_BRANCH_STATES = (STATE_ALREADY, STATE_CHECKED_OUT, STATE_EMPTY_REPOSITORY)

SETUP_TIMEOUT = 900
PROBE_TIMEOUT = 60
MAX_OUTPUT = 2000


def _env(root: Path, path_dirs: list[str]) -> dict[str, str]:
    prepend = [str((root / item).resolve()) for item in path_dirs if (root / item).resolve().is_relative_to(root)]
    env = {**os.environ, "PIP_REQUIRE_VIRTUALENV": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    env["PATH"] = os.pathsep.join([*prepend, env.get("PATH", "")])
    if path_dirs:
        env["VIRTUAL_ENV"] = str((root / path_dirs[0]).parent.resolve())
    return env


REFUSED_EXIT = 126  # "cannot execute": the server-build guard refused the command, nothing ran


async def _run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
    """Every probe and setup command of this server copy: refused when it runs build/test tooling or repository code
    (``foreign_build_guard``; the setup is a pip/npm install, a probe imports the repository), so the
    environment is ``not_ready`` with the plain message and the step pauses the run."""
    from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE, SERVER_BUILD_NOT_ALLOWED

    from ...execution_runtime import command_audit
    from ...execution_runtime.foreign_build_guard import guard_server_command
    from ...execution_runtime.server_env import server_command_env

    if guard_server_command(argv, where="workspace.prepare", audit={"cwd": str(cwd)}) is not None:
        try:
            await command_audit.record(argv, verdict="refused", where="workspace.prepare",
                                       reason=SERVER_BUILD_NOT_ALLOWED)
        except command_audit.CommandAuditUnavailableError:
            pass  # refused either way
        return REFUSED_EXIT, SERVER_BUILD_MESSAGE
    try:
        handle = await command_audit.record(argv, verdict="executed", where="workspace.prepare")
    except command_audit.CommandAuditUnavailableError:
        return REFUSED_EXIT, "The command was not run: its audit record could not be written."
    code, output = await _spawn(argv, cwd=cwd, env=server_command_env(env), timeout=timeout)
    await command_audit.record_exit(handle, code, timed_out=code == 124)
    return code, output


async def _spawn(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                       stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        return 127, f"{argv[0]}: {exc.strerror or 'cannot run'}"
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        return 124, f"timed out after {timeout} s"
    return int(process.returncode or 0), output.decode(errors="replace")[-MAX_OUTPUT:]


def _no_ref(ls_remote: str) -> bool:
    from ...knowledge.sources.sync.git_clone import advertises_no_ref

    return advertises_no_ref(ls_remote.encode("ascii", "replace"))


async def _unborn(root: Path, branch: str, git_env: dict[str, str] | None) -> dict[str, Any] | None:
    """A working copy without a commit: ``empty_repository`` when ``origin`` has no ref either, ``None`` when it
    has refs (prepared as any other folder), ``unavailable`` when ``origin`` cannot be read (module doc)."""
    code, refs, error = await git(root, "ls-remote", "origin", env=git_env)
    if code != 0:
        return {"state": "unavailable", "name": branch,
                "detail": f"the folder has no commit and origin could not be read: {error.strip()[:300]}"}
    if not _no_ref(refs):
        return None
    if not branch:
        return {"state": "unavailable", "name": branch, "detail": "the run names no branch to start"}
    code, _, error = await git(root, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    if code != 0:
        return {"state": "unavailable", "name": branch, "detail": error.strip()[:300]}
    return {"state": STATE_EMPTY_REPOSITORY, "name": branch, "head": "",
            "detail": "the repository has no commits yet: the run's branch starts with its first commit"}


async def prepare_branch(root: Path, branch: str, *, git_env: dict[str, str] | None = None) -> dict[str, Any]:
    """``git_env``: the environment of the fetches from ``origin`` (its credential, module doc); ``None`` fetches
    with this process's environment."""
    if (await git(root, "rev-parse", "--is-inside-work-tree"))[0] != 0:
        return {"state": "unavailable", "name": branch, "detail": "the folder is not a git working copy"}
    code, current, _ = await git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:  # an unborn HEAD: no commit in the folder yet
        empty = await _unborn(root, branch, git_env)
        if empty is not None:
            return empty
        current = ""
    current = current.strip()
    if current == branch:
        return {"state": STATE_ALREADY, "name": branch, "head": (await git(root, "rev-parse", "HEAD"))[1].strip()}
    _, status, _ = await git(root, "status", "--porcelain", "--untracked-files=no")
    dirty = [line[3:] for line in status.splitlines() if line.strip()]
    if dirty:
        return {"state": "dirty", "name": branch, "current": current, "dirty_files": dirty[:20],
                "detail": f"the folder is on '{current}' with uncommitted changes to {len(dirty)} tracked file(s)"}
    fetched, _, fetch_error = await git(root, "fetch", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                                        env=git_env)
    local = (await git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"))[0] == 0
    if local:
        code, _, error = await git(root, "checkout", branch)
        if code == 0 and fetched == 0:
            await git(root, "merge", "--ff-only", f"origin/{branch}")  # behind → fast-forward; diverged → kept
    elif fetched == 0:
        code, _, error = await git(root, "checkout", "-b", branch, "--track", f"origin/{branch}")
    else:
        return {"state": "unavailable", "name": branch, "current": current,
                "detail": f"the branch could not be fetched from origin: {fetch_error.strip()[:300]}"}
    if code != 0:
        return {"state": "unavailable", "name": branch, "current": current, "detail": error.strip()[:300]}
    return {"state": STATE_CHECKED_OUT, "name": branch, "previous": current,
            "head": (await git(root, "rev-parse", "HEAD"))[1].strip()}


async def _probe(root: Path, probe: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    if probe.get("which"):
        name = str(probe["which"])
        found = (root / name).is_file() and os.access(root / name, os.X_OK) if "/" in name else bool(
            shutil.which(name, path=env["PATH"]))
        return {"what": probe["what"], "ok": found, "detail": "" if found else f"{name}: command not found"}
    argv = ["/bin/sh", "-c", str(probe["shell"])] if probe.get("shell") else list(probe.get("argv") or [])
    code, output = await _run(argv, cwd=root, env=env, timeout=PROBE_TIMEOUT)
    detail = output.strip()[-300:] or (f"exit {code}" if code else "")
    if code == 3 and not probe.get("shell"):
        detail = f"module '{probe['what'].rsplit(' ', 1)[-1]}' is not installed for {argv[0]}"
    return {"what": probe["what"], "ok": code == 0, "detail": detail}


async def _exclude(root: Path, patterns: list[str]) -> None:
    """The environment's directories (``.venv``) and the test report never become part of the change: a local
    exclude, not a commit."""
    code, target, _ = await git(root, "rev-parse", "--git-path", "info/exclude")
    if not patterns or code != 0:
        return
    exclude = root / target.strip()
    lines = exclude.read_text().splitlines() if exclude.is_file() else []
    missing = [pattern for pattern in patterns if pattern not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, *missing]) + "\n")


async def prepare_environment(root: Path, environment: dict[str, Any] | None) -> dict[str, Any]:
    if not environment:
        return {"state": "not_declared", "probes": [], "setup": [],
                "reason": "the repository declares no test environment and none could be derived from its CI"}
    from .spec import local_excludes

    await _exclude(root, list(environment.get("exclude") or local_excludes(environment)))
    env = _env(root, list(environment.get("path") or []))
    results = [await _probe(root, probe, env) for probe in environment.get("probes") or []]
    setup_log: list[dict[str, Any]] = []
    if not all(item["ok"] for item in results) and environment.get("setup"):
        for command in environment["setup"]:
            if why := refused_command(command):
                setup_log.append({"command": command, "exit_code": None, "output": f"refused: {why}", "seconds": 0})
                break
            started = time.monotonic()
            code, output = await _run(["/bin/sh", "-c", command], cwd=root, env=env, timeout=SETUP_TIMEOUT)
            setup_log.append({"command": command, "exit_code": code, "output": output[-MAX_OUTPUT:],
                              "seconds": round(time.monotonic() - started, 1)})
            if code != 0:
                break
        results = [await _probe(root, probe, env) for probe in environment.get("probes") or []]
    failed = [item for item in results if not item["ok"]]
    if not failed:
        return {"state": "ready", "probes": results, "setup": setup_log}
    reason = "; ".join(f"{item['what']}: {item['detail']}" for item in failed)
    if setup_log and setup_log[-1].get("exit_code") not in (0,):
        reason += f"; setup '{setup_log[-1]['command'][:120]}' failed: {str(setup_log[-1]['output']).strip()[-300:]}"
    elif not environment.get("setup"):
        reason += "; the repository declares no environment setup"
    return {"state": "not_ready", "probes": results, "setup": setup_log, "reason": reason[:1500]}


# A server run whose workflow neither builds nor tests (``server_build.builds_or_tests``, e.g. spec writing): the
# environment stage has nothing to do, and its probes would only meet the server-build guard. The branch step stays.
ENVIRONMENT_NOT_NEEDED: dict[str, Any] = {
    "state": "not_needed", "probes": [], "setup": [],
    "reason": "this workflow neither builds nor tests on the server, so its test environment is not prepared"}


async def prepare_locally(root: Path, spec: dict[str, Any], *,
                          git_env: dict[str, str] | None = None) -> dict[str, Any]:
    """The report of preparing ``root`` for ``spec`` (branch, then environment on that branch); ``git_env``: the
    credential environment of the fetches from ``origin`` (``origin_auth.origin_git_env``)."""
    root = Path(root).resolve()
    branch = await prepare_branch(root, str(spec.get("branch") or ""), git_env=git_env)
    report: dict[str, Any] = {"root": str(root), "branch": branch, "runtime": "server"}
    if branch["state"] in READY_BRANCH_STATES and spec.get("run_id"):
        report["wip"] = await restore_run_wip(root, str(spec["run_id"]), git_env=git_env)
    if branch["state"] in READY_BRANCH_STATES:
        report["environment"] = (ENVIRONMENT_NOT_NEEDED if spec.get("environment_needed") is False
                                 else await prepare_environment(root, spec.get("environment")))
    return report


WIP_PREFIX = "octryx-wip"
_SHA = re.compile(r"^[0-9a-f]{40}$")


async def _changed(root: Path, older: str, newer: str) -> set[str]:
    _, listed, _ = await git(root, "diff", "--name-only", "-z", "--no-renames", older, newer)
    return {name for name in listed.split("\0") if name}


async def restore_run_wip(root: Path, run_id: str, *, git_env: dict[str, str] | None = None) -> dict[str, Any]:
    """The run's work in progress (``octryx-wip/<run id>``, pushed by the device client after each turn) in the working
    tree only: the WIP's own changes against the commit it was taken on, and only where the branch has not changed
    the file since; never over the folder's own uncommitted changes. Otherwise
    the whole WIP tree checked out over a branch that had moved on (item merges) took the merged files away and the
    next work-plan commit deleted them (the launcher's ``run_wip.restore_run_wip`` is the same rule)."""
    segment = re.sub(r"[^A-Za-z0-9._-]", "-", run_id).strip("-.")[:60] or "x"
    branch, local = f"{WIP_PREFIX}/{segment}", f"refs/octryx-wip/{segment}"
    await git(root, "fetch", "--no-tags", "--quiet", "origin", f"+refs/heads/{branch}:{local}", env=git_env)
    code, sha, _ = await git(root, "rev-parse", "--verify", "--quiet", local)
    sha = sha.strip()
    if code != 0 or not _SHA.match(sha):
        return {"state": "absent", "branch": branch}
    _, status, _ = await git(root, "status", "--porcelain", "--untracked-files=no")
    if status.strip():
        return {"state": "dirty", "branch": branch, "sha": sha}
    _, head, _ = await git(root, "rev-parse", "HEAD")
    head = head.strip()
    _, base, _ = await git(root, "merge-base", sha, head)  # the commit the WIP was taken on, as the branch has it
    base = base.strip()
    if not _SHA.match(base):
        return {"state": "stale", "branch": branch, "sha": sha}
    moved = await _changed(root, base, head) if base != head else set()
    paths = sorted(await _changed(root, base, sha) - moved)
    if not paths:
        return {"state": "unchanged", "branch": branch, "sha": sha}
    code, _, error = await git(root, "restore", f"--source={sha}", "--worktree", "--pathspec-from-file=-",
                               "--pathspec-file-nul", stdin="\0".join(paths).encode(),
                               env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"})
    if code != 0:
        return {"state": "failed", "branch": branch, "sha": sha, "reason": error.strip()[:200]}
    return {"state": "restored", "branch": branch, "sha": sha, "files": len(paths)}


__all__ = ["ENVIRONMENT_NOT_NEEDED", "READY_BRANCH_STATES", "STATE_EMPTY_REPOSITORY", "prepare_branch",
           "prepare_environment", "prepare_locally", "restore_run_wip"]
