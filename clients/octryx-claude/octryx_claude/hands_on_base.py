"""Red regression scenarios run once more on the run's base commit in a temporary worktree.
One red on the base too is ``pre_existing``; one green there stays red, because this work broke it."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

GIT_TIMEOUT = 120


def _git(root: Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=GIT_TIMEOUT,
                              check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def failed_regressions(scenarios: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[str]:
    regression = {str(item.get("id")) for item in scenarios if item.get("part") == "regression"}
    return [str(item.get("id")) for item in results if not item.get("passed") and (
        str(item.get("id")) in regression or str(item.get("id")).startswith("repo:"))]


def failed_features(scenarios: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[str]:
    by_id = {str(item.get("id")): item for item in scenarios if item.get("part") == "feature"}
    return [str(item.get("id")) for item in results if not item.get("passed") and str(item.get("id")) in by_id
            and before_target(by_id[str(item.get("id"))], item.get("failed_step"))]


def target_step(scenario: dict[str, Any]) -> int:
    steps = [*list(scenario.get("seed") or []), *list(scenario.get("steps") or [])]
    marked = [index for index, step in enumerate(steps) if step.get("symptom")]
    expects = [index for index, step in enumerate(steps) if str(step.get("do", "")).startswith("expect")]
    return (marked or expects or [len(steps)])[0 if marked else -1]


def before_target(scenario: dict[str, Any], failed_step: Any) -> bool:
    return type(failed_step) is int and failed_step < target_step(scenario)


def invalid_reason(scenario: dict[str, Any], failed_step: int) -> str:
    seed = list(scenario.get("seed") or [])
    steps = [*seed, *list(scenario.get("steps") or [])]
    step = steps[failed_step] if 0 <= failed_step < len(steps) else {}
    target = str(step.get("text") or step.get("label") or "").strip().casefold()
    created = {str(item.get("value") or item.get("text") or "").strip().casefold() for item in seed}
    if seed and failed_step >= len(seed) and target and target in created:
        return "data_lost_after_restart"
    return "setup_fails_on_base"


def recheck_on_base(root: Path, folder: Path, base_sha: str, scenarios: list[dict[str, Any]], failed: list[str],
                    run: Any) -> dict[str, dict[str, Any]]:
    from . import hands_on_repo  # noqa: PLC0415

    if not base_sha or not failed:
        return {}
    root = Path(root).resolve()
    worktree = Path(tempfile.mkdtemp(prefix="octryx-hands-on-base-")) / "tree"
    if not _git(root, "worktree", "add", "--detach", str(worktree), base_sha):
        return {}
    try:
        base_folder = worktree / Path(folder).resolve().relative_to(root)
        if not base_folder.is_dir():
            return {}  # the app is new in this work: nothing on the base to compare with
        kept, _broken = hands_on_repo.load(base_folder)
        wanted = set(failed)
        again = [item for item in [*scenarios, *kept] if str(item.get("id")) in wanted]
        results = run(base_folder, again) if again else None
        return {str(item.get("id")): item for item in results or [] if not item.get("passed")}
    finally:
        _git(root, "worktree", "remove", "--force", str(worktree))
        shutil.rmtree(worktree.parent, ignore_errors=True)  # our own temporary folder


def run_in(base_folder: Path, scenarios: list[dict[str, Any]], environment: dict[str, Any], channel: str | None,
           budget: float) -> list[dict[str, Any]] | None:
    from . import environment_file  # noqa: PLC0415
    from .hands_on import run_scenarios
    from .hands_on_app import (
        start_app,
        stop_app,  # noqa: PLC0415
    )
    from .pipeline_commands import _env  # noqa: PLC0415
    from .serve_port import on_free_port  # noqa: PLC0415

    serve, env = on_free_port(environment["serve"], _env(base_folder, list(environment.get("path") or []),
                                                          environment))
    ready, _log = environment_file.setup(base_folder, environment, env)
    if not ready:
        return None
    shots = Path(tempfile.mkdtemp(prefix="octryx-hands-on-base-shots-"))
    try:
        process, problem = start_app(serve, base_folder, env, shots / "serve.log")
        if problem:
            return None
        try:
            results, problem = run_scenarios(scenarios, serve["url"], channel, shots, budget)
        finally:
            stop_app(process, serve["url"])
        return None if problem else results
    finally:
        shutil.rmtree(shots, ignore_errors=True)


def recheck(view: dict[str, Any], root: Path, folder: Path, scenarios: list[dict[str, Any]],
            results: list[dict[str, Any]], environment: dict[str, Any], channel: str | None,
            budget: float) -> list[dict[str, Any]]:
    base_sha = str(view.get("base_sha") or "")
    regressions = failed_regressions(scenarios, results)
    features = failed_features(scenarios, results)
    if not (regressions or features) or not base_sha:
        return results
    again = recheck_on_base(root, folder, base_sha, scenarios, [*regressions, *features],
                            lambda tree, items: run_in(tree, items, environment, channel, budget))
    return mark(results, again, base_sha, scenarios, set(features))


def mark(results: list[dict[str, Any]], on_base: dict[str, dict[str, Any]], base_sha: str,
         scenarios: list[dict[str, Any]] | None = None, features: set[str] | None = None) -> list[dict[str, Any]]:
    by_id = {str(item.get("id")): item for item in scenarios or []}
    marked = []
    for item in results:
        ident = str(item.get("id"))
        base = on_base.get(ident)
        if base is None:
            marked.append(item)
        elif ident not in (features or set()):
            marked.append({**item, "pre_existing": base_sha})
        elif base.get("failed_step") == item.get("failed_step") and before_target(by_id[ident], base.get(
                "failed_step")):
            marked.append({**item, "invalid": {"reason": invalid_reason(by_id[ident], int(base["failed_step"])),
                                               "base": base_sha, "error": str(base.get("error") or "")[:400]}})
        else:
            marked.append(item)  # red on the base at another step: this work's to fix
    return marked


__all__ = ["failed_regressions", "mark", "recheck", "recheck_on_base", "run_in"]
