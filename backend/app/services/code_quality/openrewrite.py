from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.code_quality.helpers import (
    detect_validation_blockers,
    list_openrewrite_report_files,
    resolve_gradle_command,
    resolve_maven_command,
    resolve_validation_gates,
    truncate,
)
from app.services.code_quality.repo_files import OPENREWRITE_DEFAULT_MAVEN_PLUGIN_VERSION
from app.services.code_quality.run_status import run_did_not_finish, run_outcome_fields, unfinished_run_blocker
from app.services.process_output_redaction import redact_process_output

RunExecFn = Callable[..., Awaitable[dict[str, Any]]]
WhichFn = Callable[[str], str | None]

_GRADLE_MARKERS = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
_DRY_RUN_MESSAGE = "Run the selected OpenRewrite recipes in dry-run mode before applying changes."


def _refusal(error: str, repo_root: Path, config: dict[str, Any], validation_gates: list[Any]) -> dict[str, Any]:
    return {
        "error": error,
        "repo_root": str(repo_root),
        "config": config,
        "validation_gates": validation_gates,
        "validation_blockers": [],
    }


def _dry_run_required(
    repo_root: Path, config: dict[str, Any], validation_gates: list[Any], recipes: list[str], artifacts: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "error": "OpenRewrite dry-run is required before applying recipes",
        "blocker": {
            "code": "openrewrite_dry_run_required",
            "message": _DRY_RUN_MESSAGE,
        },
        "repo_root": str(repo_root),
        "config": config,
        "recipes": recipes,
        "recipe_artifacts": artifacts,
        "dry_run": dry_run,
        "validation_gates": validation_gates,
        "validation_blockers": [
            {
                "code": "openrewrite_dry_run_required",
                "severity": "blocking",
                "tool_name": "run_openrewrite_recipe",
                "message": _DRY_RUN_MESSAGE,
                "question": "Should I run an OpenRewrite dry run first and review the results?",
            }
        ],
    }


def _build_command(
    repo_root: Path, *, recipes: list[str], artifacts: list[str], plugin_version: str, dry_run: bool,
    export_datatables: bool, which_fn: WhichFn,
) -> list[str] | str:
    if (repo_root / "pom.xml").exists():
        launcher = resolve_maven_command(repo_root, which_fn=which_fn)
        if not launcher:
            return "Maven is required to run OpenRewrite"
        goal = f"org.openrewrite.maven:rewrite-maven-plugin:{plugin_version}:{'dryRun' if dry_run else 'run'}"
        command = [
            *launcher,
            "-q",
            goal,
            f"-Drewrite.activeRecipes={','.join(recipes)}",
            f"-Drewrite.exportDatatables={'true' if export_datatables else 'false'}",
        ]
    elif any((repo_root / marker).exists() for marker in _GRADLE_MARKERS):
        launcher = resolve_gradle_command(repo_root, which_fn=which_fn)
        if not launcher:
            return "Gradle is required to run OpenRewrite"
        goal = "rewriteDryRun" if dry_run else "rewriteRun"
        command = [
            *launcher,
            goal,
            f"-Drewrite.activeRecipe={','.join(recipes)}",
            f"-Drewrite.exportDatatables={'true' if export_datatables else 'false'}",
        ]
    else:
        return "No supported Java build detected for OpenRewrite"
    if artifacts:
        command.append(f"-Drewrite.recipeArtifactCoordinates={','.join(artifacts)}")
    return command


def _run_result(
    result: dict[str, Any], command: list[str], *, repo_root: Path, language: str, config: dict[str, Any],
    validation_gates: list[Any], recipes: list[str], artifacts: list[str], plugin_version: str, dry_run: bool,
) -> dict[str, Any]:
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    combined = "\n".join(part for part in (stdout, stderr) if part)
    # A run that did not finish (timed out, refused, not started) carries ``error``: the upgrade
    # gates never read it as a dry run that succeeded or as recipes that were applied.
    unfinished = run_did_not_finish(result)
    return {
        "repo_root": str(repo_root),
        "language": language,
        "build_tool": "maven" if (repo_root / "pom.xml").exists() else "gradle",
        "recipes": recipes,
        "recipe_artifacts": artifacts,
        "plugin_version": plugin_version,
        "dry_run": dry_run,
        "command": result.get("command", command),
        "exit_code": result.get("exit_code"),
        **run_outcome_fields(result),
        "changed": not unfinished
        and ("These recipes would make changes" in combined or "Applying recipes would make changes" in combined),
        "report_files": [] if unfinished else list_openrewrite_report_files(repo_root),
        # The OpenRewrite run log (dry-run diff, recipe results) is the product result the agent reads.
        "stdout": truncate(redact_process_output(stdout)),
        "stderr": truncate(redact_process_output(stderr)),
        "execution_runtime": result.get("execution_runtime"),
        "validation_gates": validation_gates,
        "validation_blockers": (
            [unfinished_run_blocker(result, tool_name="run_openrewrite_recipe")]
            if unfinished
            else detect_validation_blockers(
                combined,
                exit_code=result.get("exit_code"),
                tool_name="run_openrewrite_recipe",
                config=config,
            )
        ),
    }


async def run_openrewrite_recipe_impl(
    *,
    cwd: Path,
    recipes: list[str] | None = None,
    recipe_artifacts: list[str] | None = None,
    dry_run: bool = False,
    timeout_sec: int = 300,
    export_datatables: bool = True,
    project_config: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    load_config_fn: Callable[..., dict[str, Any]],
    run_exec_fn: RunExecFn,
    which_fn: WhichFn,
) -> dict[str, Any]:
    config = load_config_fn(cwd, project_config=project_config)
    repo_root = Path(str(config.get("repo_root") or cwd)).resolve()
    language = str(config.get("language") or "unknown").lower()
    validation_gates = resolve_validation_gates(config)
    selected_recipes = [
        str(item).strip() for item in (recipes or config.get("openrewrite_recipes") or []) if str(item).strip()
    ]
    selected_artifacts = [
        str(item).strip()
        for item in (recipe_artifacts or config.get("openrewrite_recipe_artifacts") or [])
        if str(item).strip()
    ]
    plugin_version = str(config.get("openrewrite_plugin_version") or OPENREWRITE_DEFAULT_MAVEN_PLUGIN_VERSION).strip()

    if language != "java":
        return _refusal("OpenRewrite is currently supported for Java repositories only", repo_root, config,
                        validation_gates)
    if not selected_recipes:
        return _refusal("At least one OpenRewrite recipe is required", repo_root, config, validation_gates)
    if bool(config.get("openrewrite_dry_run_required")) and not dry_run:
        return _dry_run_required(repo_root, config, validation_gates, selected_recipes, selected_artifacts, dry_run)

    command = _build_command(
        repo_root, recipes=selected_recipes, artifacts=selected_artifacts, plugin_version=plugin_version,
        dry_run=dry_run, export_datatables=export_datatables, which_fn=which_fn,
    )
    if isinstance(command, str):
        return _refusal(command, repo_root, config, validation_gates)
    result = await run_exec_fn(
        command,
        cwd=repo_root,
        timeout_sec=timeout_sec,
        db=db,
        project_config=project_config,
    )
    return _run_result(
        result, command, repo_root=repo_root, language=language, config=config, validation_gates=validation_gates,
        recipes=selected_recipes, artifacts=selected_artifacts, plugin_version=plugin_version, dry_run=dry_run,
    )
