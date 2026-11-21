"""SCIP planning and build helpers for code intelligence."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.code_intelligence.process import _run_command
from app.services.code_intelligence.semantic_store import (
    _build_semantic_index,
    _finalize_scip_output,
    _parse_scip_snapshot_annotations,
    _scip_stage_dir,
    _semantic_artifact_path,
    _write_semantic_index,
)
from app.services.code_intelligence.storage_capabilities import _find_binary
from app.services.code_intelligence.storage_constants import _SCIP_BUILDABLE_LANGUAGES
from app.services.code_intelligence.storage_runtime import (
    _coerce_list,
    _scip_index_dir,
    _scip_native_index_path,
    _scip_snapshot_dir,
)
from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_MESSAGE, SERVER_BUILD_NOT_ALLOWED


async def _maybe_build_java_native_scip_index(*, repository_id: str) -> dict[str, Any]:
    binary = _find_binary("scip-java")
    if not binary:
        return {"status": "skipped", "reason": "scip-java not installed"}
    scip_dir = _scip_index_dir(repository_id)
    if not (scip_dir / "java.scip").exists():
        return {"status": "skipped", "reason": "java.scip not found"}
    snapshot_dir = _scip_snapshot_dir(repository_id, "java")
    result = await _run_command(
        [binary, "snapshot", "--output", str(snapshot_dir), str(scip_dir)],
        cwd=scip_dir,
        timeout_sec=300,
    )
    if result["exit_code"] != 0:
        # Snapshot tool output is diagnostics only: closed code and exit status.
        return {
            "status": "error",
            "reason": "scip_java_snapshot_failed",
            "exit_code": result["exit_code"],
            "snapshot_dir": str(snapshot_dir),
        }
    native_index = await asyncio.to_thread(_parse_scip_snapshot_annotations, snapshot_dir)
    native_index_path = _scip_native_index_path(repository_id, "java")
    native_index_path.write_text(json.dumps(native_index, indent=2), encoding="utf-8")
    return {
        "status": "ready",
        "snapshot_dir": str(snapshot_dir),
        "native_index_path": str(native_index_path),
        "files_indexed": int(native_index.get("files_indexed") or 0),
    }


def _language_groups(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in _coerce_list(snapshot.get("files")):
        if not isinstance(item, dict):
            continue
        language = str(item.get("language") or "").strip()
        path = str(item.get("path") or "").strip()
        if language and path:
            grouped[language].append(path)
    return dict(grouped)


def _resolve_compile_commands(repo_root: Path) -> Path | None:
    for candidate in (
        repo_root / "compile_commands.json",
        repo_root / "build" / "compile_commands.json",
        repo_root / "out" / "compile_commands.json",
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _java_build_tool_present(repo_root: Path) -> bool:
    return any(
        (repo_root / candidate).exists()
        for candidate in ("pom.xml", "build.gradle", "build.gradle.kts", "mvnw", "gradlew")
    )


# Indexers driven by the repository's build: ``scip-java index`` runs its Maven/Gradle build (plugins, ``mvnw``/
# ``gradlew``), ``scip-clang`` the compiler with the repository's own compile flags (``-fplugin``). The indexer runs on
# the server, so neither runs (``foreign_build_guard``); the outline/graph index stays. Their plans
# below are kept for the sandbox runtime.
SERVER_REFUSED_SCIP_LANGUAGES = frozenset({"java", "c", "cpp"})


def _plan_scip_command(*, repository_id: str, repo_root: Path, language: str) -> dict[str, Any]:
    if language in SERVER_REFUSED_SCIP_LANGUAGES:
        return {"status": "skipped", "reason": SERVER_BUILD_NOT_ALLOWED, "message": SERVER_BUILD_MESSAGE}
    stage_dir = _scip_stage_dir(repository_id, language)
    output_path = stage_dir / f"{language}.scip"
    if language == "go":
        binary = _find_binary("scip-go")
        if not binary:
            return {"status": "skipped", "reason": "scip-go not installed"}
        return {"status": "planned", "command": [binary, "-o", str(output_path)], "output_path": str(output_path)}
    if language == "python":
        binary = _find_binary("scip-python")
        if not binary:
            return {"status": "skipped", "reason": "scip-python not installed"}
        return {
            "status": "planned",
            "command": [binary, "index", ".", "--project-name", repo_root.name, "--output", str(output_path)],
            "output_path": str(output_path),
        }
    if language in {"typescript", "javascript"}:
        binary = _find_binary("scip-typescript")
        if not binary:
            return {"status": "skipped", "reason": "scip-typescript not installed"}
        command = [binary, "index", "--output", str(output_path)]
        if not (repo_root / "tsconfig.json").exists() and not (repo_root / "jsconfig.json").exists():
            command.extend(["--infer-tsconfig"])
        return {"status": "planned", "command": command, "output_path": str(output_path)}
    if language in {"c", "cpp"}:
        binary = _find_binary("scip-clang")
        if not binary:
            return {"status": "skipped", "reason": "scip-clang not installed"}
        compile_commands = _resolve_compile_commands(repo_root)
        if compile_commands is None:
            return {"status": "skipped", "reason": "compile_commands.json not found"}
        return {
            "status": "planned",
            "command": [binary, f"--compdb-path={compile_commands}", f"--index={output_path}"],
            "output_path": str(output_path),
        }
    if language == "java":
        binary = _find_binary("scip-java")
        if not binary:
            return {"status": "skipped", "reason": "scip-java not installed"}
        if not _java_build_tool_present(repo_root):
            return {"status": "skipped", "reason": "no Maven or Gradle build detected"}
        target_root = stage_dir / "semanticdb-targetroot"
        target_root.mkdir(parents=True, exist_ok=True)
        return {
            "status": "planned",
            "command": [binary, "index", "--output", str(output_path), "--targetroot", str(target_root)],
            "output_path": str(output_path),
        }
    return {"status": "skipped", "reason": f"unsupported language: {language}"}


async def _maybe_build_scip_indices(*, repository_id: str, repo_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    output_dir = _semantic_artifact_path(repository_id).parent
    languages = sorted(set(_language_groups(snapshot)))
    results: list[dict[str, Any]] = []
    ready_languages: set[str] = set()
    native_index_paths: dict[str, str] = {}
    snapshot_dirs: dict[str, str] = {}
    for language in languages:
        if language not in _SCIP_BUILDABLE_LANGUAGES and language != "java":
            continue
        plan = _plan_scip_command(repository_id=repository_id, repo_root=repo_root, language=language)
        if plan.get("status") != "planned":
            results.append({"language": language, **plan})
            continue
        command = [str(part) for part in plan["command"]]
        result = await _run_command(command, cwd=repo_root, timeout_sec=300)
        artifact_path = None
        status = "error"
        if result["exit_code"] == 0:
            staged_output_path = Path(str(plan.get("output_path"))) if plan.get("output_path") else None
            artifact_path = _finalize_scip_output(
                repo_root=repo_root,
                output_dir=output_dir,
                language=language,
                staged_output_path=staged_output_path,
            )
            status = "ready" if artifact_path else "warning"
            if artifact_path:
                ready_languages.add(language)
                if language == "java":
                    native = await _maybe_build_java_native_scip_index(repository_id=repository_id)
                    if native.get("status") == "ready":
                        native_index_paths[language] = str(native.get("native_index_path") or "")
                        snapshot_dirs[language] = str(native.get("snapshot_dir") or "")
        results.append(
            {
                "language": language,
                "status": status,
                "artifact_path": artifact_path,
                "command": command,
                # Indexer output is diagnostics only; the exit status and closed reason stand for it.
                "exit_code": result["exit_code"],
                "reason": None if result["exit_code"] == 0 else "indexer_failed",
            }
        )
    semantic_index_path = None
    if ready_languages:
        semantic_index = _build_semantic_index(snapshot, ready_languages=ready_languages)
        semantic_index_path = _write_semantic_index(repository_id=repository_id, semantic_index=semantic_index)
    return {
        "status": "ready" if any(item.get("status") == "ready" for item in results) else "skipped",
        "output_dir": str(output_dir),
        "languages": results,
        "semantic_index_path": semantic_index_path,
        "native_index_paths": native_index_paths,
        "snapshot_dirs": snapshot_dirs,
    }
