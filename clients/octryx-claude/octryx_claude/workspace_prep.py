"""Prepare the launch folder before the agent starts: check the repository, put it on the run's branch, prepare
the environment and report the facts (``POST sessions/workspace-preparation``); the platform routes the run."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import browser, git_gateway
from .git_gateway import GatewaySource
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
            bundle_source: BundleSource | None = None, gateway: GatewaySource | None = None) -> dict[str, Any] | None:
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
    branch = prepare_branch(root, str(prep.get("branch") or ""), str(prep.get("head") or "") or None, bundle_source,
                            gateway)
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


def _gateway(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, *,
             http: Any) -> GatewaySource | None:
    from .codex_config import agent_mode  # noqa: PLC0415

    path = str((preparation_of(contract) or {}).get("git_gateway") or "")
    return git_gateway.source_for(state, context, path, http=http) if path and agent_mode() else None


def prepare_for_session(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, folder: str, *,
                        http: Any, runtime: str, timeout: float = REPORT_TIMEOUT) -> tuple[dict[str, Any] | None, str]:
    def bundle_source(have: list[str]) -> dict[str, Any] | None:
        answer = call_control_plane(state, context, "POST", "/sessions/branch-bundle", http=http,
                                    timeout=BUNDLE_TIMEOUT, body={"have": have})
        return answer.body if answer.outcome == "ok" else None

    report = prepare(contract, repository_root(folder), runtime=runtime, bundle_source=bundle_source,
                     gateway=_gateway(state, context, contract, http=http))
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
    # a device turn starts only on a ready folder; a terminal starts unless the report paused the run
    return current, code if runtime == "device" or paused else ""


def prepare_terminal(state: LocalState, context: SessionContext, folder: str, env: dict[str, str]) -> str:
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
    # An editable install in a shared environment points at the main folder's sources; the item tests its own code.
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
