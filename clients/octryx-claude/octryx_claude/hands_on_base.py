"""Red regression scenarios run once more on the run's base commit.

When the pass's regression scenarios fail, the launcher checks out the
base commit in a temporary git worktree, runs the app folder's setup and serve there and repeats only those
scenarios. One that fails on the base too is reported ``pre_existing`` (the platform reports it, never blocks on it);
one that passes there stays red: this work broke it. Feature scenarios never run on the base (the feature is new).
"""

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
    """The ids of the regression scenarios (the platform's ``part: regression`` and the repository's ``repo:``) that
    failed in this pass."""
    regression = {str(item.get("id")) for item in scenarios if item.get("part") == "regression"}
    return [str(item.get("id")) for item in results if not item.get("passed") and (
        str(item.get("id")) in regression or str(item.get("id")).startswith("repo:"))]


def failed_features(scenarios: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[str]:
    """The ids of the platform's feature scenarios that failed in this pass before the step they check."""
    by_id = {str(item.get("id")): item for item in scenarios if item.get("part") == "feature"}
    return [str(item.get("id")) for item in results if not item.get("passed") and str(item.get("id")) in by_id
            and before_target(by_id[str(item.get("id"))], item.get("failed_step"))]


def target_step(scenario: dict[str, Any]) -> int:
    """The index (seed and steps, as a result counts them) of the step a feature scenario checks: its symptom step,
    else its last expect step."""
    steps = [*list(scenario.get("seed") or []), *list(scenario.get("steps") or [])]
    marked = [index for index, step in enumerate(steps) if step.get("symptom")]
    expects = [index for index, step in enumerate(steps) if str(step.get("do", "")).startswith("expect")]
    return (marked or expects or [len(steps)])[0 if marked else -1]


def before_target(scenario: dict[str, Any], failed_step: Any) -> bool:
    return type(failed_step) is int and failed_step < target_step(scenario)


def invalid_reason(scenario: dict[str, Any], failed_step: int) -> str:
    """Why a feature scenario that fails on the base before its checked step tests nothing: the data its seed
    created is gone after the restart (the app keeps no data across one), or its setup fails there too."""
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
    """The base results of ``failed`` that fail on ``base_sha`` too, by id; empty when the base cannot be checked
    out or started.

    ``run(base_folder, scenarios)`` sets up, serves and runs the scenarios in the base checkout and returns their
    results (``hands_on.execute``'s own steps), or ``None`` when the app did not start there."""
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
    """Set up, serve and run ``scenarios`` in the base checkout; ``None`` when the app did not start there. Its
    screenshots are not evidence of this work and are dropped."""
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
    """``results`` with every failed regression scenario that fails on the view's ``base_sha`` too marked, and every
    feature scenario that fails there at the same step before the step it checks marked ``invalid`` (
    : a seed's data gone after the restart; the scenario tests nothing and must not send the fix back)."""
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
    """The pass's results with each regression scenario red on the base marked ``pre_existing``, and each feature
    scenario that failed on the base at the same step, before its checked step, marked ``invalid`` with why."""
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
