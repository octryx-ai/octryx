"""Unified diff patch application tool for workspace files."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.tools.context import ToolContext
from app.tools.runtime_impl._runtime_cwd_resolution import _resolve_cwd

from ...services.error_facts import error_facts, error_text
from ..runtime_impl._runtime_execution_events import build_execution_event
from ..runtime_impl._runtime_policy import evaluate_workspace_mutation_policy
from ._code_common import _ensure_repository_for_write
from ._code_patch_hunks import PatchHunkError, apply_hunks, is_file_header, parse_hunks

PATCH_APPLY_FAILED = "patch_apply_failed"


def _file_failure(code: str, exc: BaseException) -> dict[str, Any]:
    return {"error": code, **error_facts(code, exc)}


class ApplyPatchTool:
    name = "apply_patch_workspace"
    description = (
        "Apply a unified diff patch to files in the workspace. "
        "Supports add, update, and delete operations. "
        "The patch must be in standard unified diff format (--- a/file, +++ b/file, @@ hunks)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        patch_text = str(params.get("patch") or params.get("patch_text") or "").strip()
        if not patch_text:
            return {"error": "patch or patch_text is required"}

        workspace = _resolve_cwd(
            context.workspace_root,
            ".",
            context=context,
            allow_repo_fallback=True,
            allow_missing=True,
        )
        bootstrap = await _ensure_repository_for_write(context)
        if bootstrap and bootstrap.get("status") == "error":
            return {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap}

        started_at = perf_counter()
        begin_event = build_execution_event(
            kind="patch",
            tool_name=self.name,
            command="apply unified diff patch",
            cwd=str(workspace),
            status="started",
            duration_ms=0,
            metadata={"patch_chars": len(patch_text)},
        )
        target_paths = self._target_paths(patch_text)
        policy_decision = await evaluate_workspace_mutation_policy(
            context,
            tool_name=self.name,
            target_paths=[workspace / path for path in target_paths],
        )
        if policy_decision.get("blocking"):
            end_event = build_execution_event(
                kind="patch",
                tool_name=self.name,
                command="apply unified diff patch",
                cwd=str(workspace),
                status="failed",
                duration_ms=int((perf_counter() - started_at) * 1000),
                stderr=policy_decision["reason"],
                metadata={
                    "patch_chars": len(patch_text),
                    "files": target_paths,
                    "coding_policy_decision": policy_decision,
                },
            )
            return {
                "error": policy_decision["reason"],
                "coding_policy_decision": policy_decision,
                "execution_event": end_event,
                "execution_events": [begin_event, end_event],
            }
        try:
            results = self._apply(patch_text, workspace)
        except Exception as exc:
            failure = error_text(PATCH_APPLY_FAILED, exc)
            end_event = build_execution_event(
                kind="patch",
                tool_name=self.name,
                command="apply unified diff patch",
                cwd=str(workspace),
                status="failed",
                duration_ms=int((perf_counter() - started_at) * 1000),
                stderr=failure,
                metadata={"patch_chars": len(patch_text)},
            )
            return {
                "error": failure,
                **error_facts(PATCH_APPLY_FAILED, exc),
                "execution_event": end_event,
                "execution_events": [begin_event, end_event],
            }

        errors = [item for item in results if item.get("error")]
        end_event = build_execution_event(
            kind="patch",
            tool_name=self.name,
            command="apply unified diff patch",
            cwd=str(workspace),
            status="failed" if errors else "succeeded",
            exit_code=1 if errors else 0,
            duration_ms=int((perf_counter() - started_at) * 1000),
            metadata={
                "patch_chars": len(patch_text),
                "files": [str(item.get("file") or "") for item in results],
                "applied": len([item for item in results if not item.get("error")]),
                "errors": len(errors),
            },
        )
        result = {
            "applied": len([item for item in results if not item.get("error")]),
            "errors": len(errors),
            "files": results,
            "coding_policy_decision": policy_decision,
            "execution_event": end_event,
            "execution_events": [begin_event, end_event],
        }
        if bootstrap:
            result["repository_bootstrap"] = bootstrap
        return result

    def _apply(self, patch_text: str, workspace: Path) -> list[dict[str, Any]]:
        lines = patch_text.splitlines()
        results: list[dict[str, Any]] = []
        index = 0

        while index < len(lines):
            if not is_file_header(lines, index):
                index += 1
                continue

            orig_path_raw = _strip_patch_path_prefix(lines[index][4:].strip(), "a/")
            new_path_raw = _strip_patch_path_prefix(lines[index + 1][4:].strip(), "b/")
            index += 2

            is_new = orig_path_raw == "/dev/null"
            is_delete = new_path_raw == "/dev/null"
            file_key = new_path_raw if not is_delete else orig_path_raw

            orig_file = workspace / orig_path_raw if not is_new else None
            new_file = workspace / new_path_raw if not is_delete else None

            try:
                hunks, index = parse_hunks(lines, index)
            except PatchHunkError as miss:
                results.append({"file": file_key, **miss.facts})
                while index < len(lines) and not is_file_header(lines, index):
                    index += 1
                continue

            try:
                orig_content = (
                    orig_file.read_text(encoding="utf-8").splitlines(keepends=True)
                    if orig_file and orig_file.exists()
                    else []
                )
            except Exception as exc:
                results.append({"file": file_key, **_file_failure("patch_file_read_failed", exc)})
                continue

            try:
                result_lines, hunk_facts = apply_hunks(orig_content, hunks)
            except PatchHunkError as miss:
                results.append({"file": file_key, **miss.facts})
                continue

            try:
                if is_delete:
                    if orig_file and orig_file.exists():
                        orig_file.unlink()
                    results.append({"file": file_key, "action": "deleted"})
                else:
                    assert new_file is not None
                    new_file.parent.mkdir(parents=True, exist_ok=True)
                    new_file.write_text("".join(result_lines), encoding="utf-8")
                    results.append(
                        {"file": file_key, "action": "created" if is_new else "updated", "hunks": hunk_facts}
                    )
            except Exception as exc:
                results.append({"file": file_key, **_file_failure("patch_file_write_failed", exc)})

        return results

    def _target_paths(self, patch_text: str) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        lines = patch_text.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.startswith("--- "):
                index += 1
                continue
            orig_path_raw = _strip_patch_path_prefix(lines[index][4:].strip(), "a/")
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                continue
            new_path_raw = _strip_patch_path_prefix(lines[index][4:].strip(), "b/")
            file_key = orig_path_raw if new_path_raw == "/dev/null" else new_path_raw
            if file_key and file_key != "/dev/null" and file_key not in seen:
                seen.add(file_key)
                paths.append(file_key)
            index += 1
        return paths


def _strip_patch_path_prefix(path: str, prefix: str) -> str:
    return path.removeprefix(prefix)
