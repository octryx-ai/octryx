"""Prepare the launch folder for the run before the agent starts.

The run contract names what to prepare (``preparation``: the run's branch and the repository's environment as the
platform resolved it from the Workspace's repository registration). The launcher only executes it in its own folder and
reports the facts (``POST sessions/workspace-preparation``); the platform decides and routes the run:

0. **repository**: the folder's ``origin`` must be the run's repository (``preparation.repository``: the connection's
   hosts and ``<owner>/<repo>``), checked before anything changes (``foreign`` otherwise); the report carries the
   remote without user info, and the platform checks it again;
1. **branch**: on the run's branch → kept; another branch with uncommitted changes to tracked files → ``dirty``
   (nothing is stashed, reset or overwritten — a person decides); else ``git fetch origin <branch>`` and check it out
   (the local branch, fast-forwarded when behind, or a new one tracking ``origin/<branch>``). A device without git
   credentials for origin starts the branch at the commit the platform knows it at (``preparation.head``) when the
   folder has that commit; otherwise it asks the platform for the branch as a git bundle from the platform's working
   copy (``POST sessions/branch-bundle``) and fetches that instead; only when that fails too it reports what to give
   the device;
2. **environment**: the probes the platform sent (argv lists or ``which`` an executable; never a shell, except an
   explicit declared ``check``) with the declared ``path`` (folder-relative) first on ``PATH``; when one fails and a
   setup is declared, each setup command runs in the folder (``/bin/sh -c``, ``PIP_REQUIRE_VIRTUALENV=1``, no stdin,
   bounded), refused locally when it would install outside the folder, then the probes run again. The ``path``
   directories and the declared test command's JUnit report (the server's ``exclude`` patterns) are excluded locally
   (``.git/info/exclude``), so a virtual environment or a test report never enters the change.

git runs without anything the working copy configures and never prompts. The declared ``path`` is also put first on
the agent's ``PATH`` (:func:`child_path`), so ``python -m pytest`` resolves the folder's virtual environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import browser
from .platform import PlatformResult, SessionContext, call_control_plane
from .run_contract import remember
from .state import LocalState
from .work_git import is_item_folder
from .workspace_branch import BundleSource, bootstrap, prepare_branch
from .workspace_env import environment_env, file_environment, prepare_environment
from .workspace_git import (
    _BRANCH,
    _git,
    _ok,
    _out,
    discard_earlier_run,
    drop_pushed_leftovers,
    origin_url,
    repository_refusal,
)

REPORT_TIMEOUT = 30
BUNDLE_TIMEOUT = 600  # a whole branch history can take a while on a slow link


def preparation_of(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    prep = (contract or {}).get("preparation")
    return prep if isinstance(prep, dict) and prep.get("branch") else None


def prepare(contract: dict[str, Any] | None, root: Path, *, runtime: str,
            bundle_source: BundleSource | None = None) -> dict[str, Any] | None:
    """The report for the contract's preparation in ``root``, or ``None`` when the run asks for none."""
    prep = preparation_of(contract)
    if prep is None:
        return None
    root = Path(os.path.realpath(root))
    if problem := bootstrap(root, prep.get("repository")):
        return {"node_id": prep.get("node_id"), "entry": prep.get("entry"), "root": str(root), "runtime": runtime,
                "remote_url": None, "branch": {"state": "unavailable", "name": str(prep.get("branch") or ""),
                                               "detail": problem}}
    report: dict[str, Any] = {"node_id": prep.get("node_id"), "entry": prep.get("entry"), "root": str(root),
                              "runtime": runtime, "remote_url": origin_url(root) or None}
    if foreign := repository_refusal(root, prep.get("repository")):  # checked before anything in the folder changes
        report["branch"] = {"state": "foreign", "name": str(prep.get("branch") or ""), "detail": foreign}
        return report
    if prep.get("run_commits_on_device") is False and not is_item_folder(root) and _BRANCH.match(
            str(prep.get("branch") or "")):
        if cleaned := discard_earlier_run(root, str(prep["branch"]), str(prep.get("head") or "") or None):
            report["earlier_run_cleaned"] = cleaned
    branch = prepare_branch(root, str(prep.get("branch") or ""), str(prep.get("head") or "") or None, bundle_source)
    report["branch"] = branch
    if branch["state"] in ("already", "checked_out") and (dropped := drop_pushed_leftovers(root)):
        report["leftovers_dropped"] = dropped
    run_id = str(dict((contract or {}).get("run") or {}).get("id") or "")
    if branch["state"] in ("already", "checked_out") and run_id and not is_item_folder(root) and prep.get(
            "reset_to_wip"):
        from .run_wip import reset_tree  # a change of plan: back to the work of its time (``wip_reset``)

        report["wip_reset"] = reset_tree(root, run_id, str(prep["reset_to_wip"]))
    if branch["state"] in ("already", "checked_out") and run_id and not is_item_folder(root):
        from .run_wip import restore_run_wip  # the run's work in progress from an earlier turn or another device

        report["wip"] = restore_run_wip(root, run_id)
    if branch["state"] in ("already", "checked_out"):
        from .apps import found_apps

        environment = prep.get("environment") if isinstance(prep.get("environment"), dict) else None
        report["environment"] = prepare_environment(root, environment)
        report["apps"] = found_apps(root)
    return report


def repository_root(folder: str) -> Path:
    done = _git(Path(folder), "rev-parse", "--show-toplevel")
    return Path(_out(done)) if _ok(done) and _out(done) else Path(folder)


def prepare_for_session(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, folder: str, *,
                        http: Any, runtime: str, timeout: float = REPORT_TIMEOUT) -> tuple[dict[str, Any] | None, str]:
    """Prepare, report and remember the answered contract; ``(contract, refusal code or "")``.

    A device turn starts only on a ready folder; a terminal starts unless the report paused the run."""
    def bundle_source(have: list[str]) -> dict[str, Any] | None:
        answer = call_control_plane(state, context, "POST", "/sessions/branch-bundle", http=http,
                                    timeout=BUNDLE_TIMEOUT, body={"have": have})
        return answer.body if answer.outcome == "ok" else None

    report = prepare(contract, repository_root(folder), runtime=runtime, bundle_source=bundle_source)
    if report is None:
        return contract, ""
    answer: PlatformResult = call_control_plane(state, context, "POST", "/sessions/workspace-preparation", http=http,
                                                timeout=timeout, body=report)
    if answer.outcome != "ok":
        return contract, f"workspace_preparation_{answer.reason or answer.outcome}"[:80]
    current = remember(state, context.session_key, answer.body) or contract
    if answer.state == "ready":
        return current, ""
    code = {"dirty": "workspace_dirty", "foreign": "repository_not_run_repository"}.get(
        dict(report.get("branch") or {}).get("state"), "environment_not_ready")
    paused = bool((current or {}).get("paused"))
    return current, code if runtime == "device" or paused else ""


def prepare_terminal(state: LocalState, context: SessionContext, folder: str, env: dict[str, str]) -> str:
    """An interactive launch: prepare the folder for the run it follows (if any), say what happened, set the agent's
    ``PATH``; the refusal code when the report paused the run, else ``""``."""
    import sys

    import httpx

    from .run_contract import current

    contract = current(state, context.session_key)
    prep = preparation_of(contract)
    if prep is None:
        return ""
    sys.stderr.write(f"octryx-claude: preparing this folder for the run (branch {prep['branch']})\n")
    with httpx.Client() as http:
        contract, refused = prepare_for_session(state, context, contract, folder, http=http, runtime="terminal")
    prep = preparation_of(contract) or {}
    sys.stderr.write(f"octryx-claude: folder preparation: {prep.get('state') or 'reported'}\n")
    child_path(contract, folder, env)
    return refused


def child_path(contract: dict[str, Any] | None, folder: str, env: dict[str, str]) -> None:
    """Put the declared environment's ``path`` first on the agent's ``PATH`` (in place). In an item's worktree that
    uses the main folder's environment (``work_git.share_environment``), the worktree's own ``src`` comes first on
    ``PYTHONPATH``: an editable install in that environment points at the main folder's sources, and the item must
    test its own code."""
    prep = preparation_of(contract)
    environment = prep.get("environment") if prep is not None else None
    root: Path | None = None
    if isinstance(environment, dict) and environment.get("environment_file"):
        # The repository's environment file: its ``path`` is relative to its app folder (read now, in this folder).
        root, environment = file_environment(Path(os.path.realpath(repository_root(folder))), environment)
    if isinstance(environment, dict) and environment.get("path"):
        root = root or Path(os.path.realpath(repository_root(folder)))
        prepared = environment_env(root, environment, parent=env)
        env["PATH"] = prepared["PATH"]
        if prepared.get("VIRTUAL_ENV"):
            env["VIRTUAL_ENV"] = prepared["VIRTUAL_ENV"]
        own_sources_first(Path(repository_root(folder)), environment, env)
    # Every session's test runs use the device's Chrome (or the repository's declared bundled browser).
    browser.apply(env, environment if isinstance(environment, dict) else None)


def own_sources_first(root: Path, environment: dict[str, Any], env: dict[str, str]) -> None:
    """``<worktree>/src`` first on ``PYTHONPATH`` when the worktree's environment folder is a link to another one."""
    tops = {Path(str(item)).parts[0] for item in environment.get("path") or [] if Path(str(item)).parts}
    if not is_item_folder(root) or not any((root / top).is_symlink() for top in tops if top not in (".", "..")):
        return
    source = root / "src"
    if source.is_dir():
        env["PYTHONPATH"] = os.pathsep.join([str(source), *[part for part in [env.get("PYTHONPATH", "")] if part]])


__all__ = [
    "child_path",
    "own_sources_first",
    "prepare_terminal",
    "prepare",
    "prepare_for_session",
    "preparation_of",
    "repository_root",
]
