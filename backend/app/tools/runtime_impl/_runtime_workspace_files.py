"""Workspace file IO runtime tool implementations."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.tools.context import ToolContext

from ...services.request_analysis import effective_limit_from_request_analysis
from ...services.session.workspace_sync import sync_workspace_file_after_write
from ...services.workspace_change_safety import (
    build_workspace_change_contract,
    capture_workspace_change_state,
    dirty_target_paths,
    relative_change_path,
)
from ._runtime_cli_helpers import MAX_OUTPUT_CHARS, _ensure_repository_for_write, _workspace_root
from ._runtime_cwd_resolution import _resolve_cwd
from ._runtime_execution_events import build_execution_event
from ._runtime_policy import evaluate_workspace_mutation_policy


def _write_event(tool_name: str, target_change_path: str, workspace_root: Path, started_at: float, *, status: str,
                 metadata: dict[str, Any], exit_code: int | None = None) -> dict[str, Any]:
    return build_execution_event(
        kind="write",
        tool_name=tool_name,
        command=f"write {target_change_path}",
        cwd=str(workspace_root),
        status=status,
        exit_code=exit_code,
        duration_ms=int((perf_counter() - started_at) * 1000),
        metadata=metadata,
    )


def _refused_write_records(tool_name: str, target_change_path: str, workspace_root: Path, started_at: float,
                           before_change_state: Any, *, metadata: dict[str, Any],
                           blocked_paths: list[str]) -> dict[str, Any]:
    return {
        "execution_event": _write_event(
            tool_name, target_change_path, workspace_root, started_at, status="failed", metadata=metadata,
        ),
        "workspace_change_contract": build_workspace_change_contract(
            tool_name=tool_name,
            before_state=before_change_state,
            target_paths=[target_change_path],
            blocked_paths=blocked_paths,
        ),
    }


def _written_records(tool_name: str, target_change_path: str, workspace_root: Path, started_at: float,
                     before_change_state: Any, *, final_content: str, override_dirty: bool) -> dict[str, Any]:
    after_change_state = capture_workspace_change_state(workspace_root)
    return {
        "execution_event": _write_event(
            tool_name, target_change_path, workspace_root, started_at, status="succeeded", exit_code=0,
            metadata={"target_paths": [target_change_path], "bytes_written": len(final_content.encode("utf-8"))},
        ),
        "workspace_change_contract": build_workspace_change_contract(
            tool_name=tool_name,
            before_state=before_change_state,
            after_state=after_change_state,
            target_paths=[target_change_path],
            override_dirty=override_dirty,
        ),
    }


def _with_trailing_newline(content: str, params: dict) -> str:
    final_content = content
    if params.get("ensure_trailing_newline", True) and final_content and not final_content.endswith("\n"):
        final_content += "\n"
    return final_content


class WriteWorkspaceFileTool:
    """Create or overwrite a file inside the workspace and return the written path."""

    name = "write_workspace_file"
    description = "Create or overwrite a file inside the workspace and return the written path."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        path_value = str(params.get("path") or params.get("file_path") or "").strip()
        if not path_value:
            return {"error": "path is required"}

        content = params.get("content")
        if not isinstance(content, str):
            return {"error": "content must be a string"}

        try:
            target_path = _resolve_cwd(
                context.workspace_root,
                path_value,
                context=context,
                allow_repo_fallback=True,
                allow_missing=True,
                prefer_workspace_for_missing=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        started_at = perf_counter()
        bootstrap = await _ensure_repository_for_write(context)
        if bootstrap and bootstrap.get("status") == "error":
            return {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap}
        if target_path.exists() and target_path.is_dir():
            return {"error": "path points to a directory"}
        return await self._guarded_write(params, context, target_path, content, bootstrap, started_at)

    async def _guarded_write(self, params: dict, context: ToolContext, target_path: Path, content: str,
                             bootstrap: dict[str, Any] | None, started_at: float) -> dict:
        workspace_root = _workspace_root(context)
        before_change_state = capture_workspace_change_state(workspace_root)
        target_change_path = relative_change_path(before_change_state, workspace_root, target_path)
        blocked_dirty_paths = dirty_target_paths(before_change_state, [target_change_path])
        override_dirty = bool(params.get("allow_overwrite_dirty"))
        if blocked_dirty_paths and not override_dirty:
            return {
                "error": "Refusing to overwrite a file with pre-existing uncommitted workspace changes.",
                "path": str(target_path),
                **_refused_write_records(
                    self.name, target_change_path, workspace_root, started_at, before_change_state,
                    metadata={"target_paths": [target_change_path], "blocked_paths": blocked_dirty_paths},
                    blocked_paths=blocked_dirty_paths,
                ),
            }

        policy_decision = await evaluate_workspace_mutation_policy(
            context,
            tool_name=self.name,
            target_paths=[target_path],
            proposed={target_path: content},
        )
        if policy_decision.get("blocking"):
            return {
                "error": policy_decision["reason"],
                "path": str(target_path),
                "coding_policy_decision": policy_decision,
                **_refused_write_records(
                    self.name, target_change_path, workspace_root, started_at, before_change_state,
                    metadata={"target_paths": [target_change_path], "coding_policy_decision": policy_decision},
                    blocked_paths=[target_change_path],
                ),
            }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        final_content = _with_trailing_newline(content, params)
        target_path.write_text(final_content, encoding="utf-8")
        result = {
            "path": str(target_path),
            "bytes_written": len(final_content.encode("utf-8")),
            **_written_records(
                self.name, target_change_path, workspace_root, started_at, before_change_state,
                final_content=final_content, override_dirty=override_dirty,
            ),
            "coding_policy_decision": policy_decision,
        }
        return await self._after_write(result, params, context, target_path, bootstrap)

    async def _after_write(self, result: dict, params: dict, context: ToolContext, target_path: Path,
                           bootstrap: dict[str, Any] | None) -> dict:
        result["workspace_sync"] = await sync_workspace_file_after_write(
            db=context.db,
            session_id=context.session_id,
            workspace_root=context.workspace_root,
            file_path=target_path,
            content_type="text/plain; charset=utf-8",
        )
        if params.get("auto_check"):
            from app.tools.code_impl._code_syntax import CheckFileSyntaxTool

            syntax = await CheckFileSyntaxTool().execute({"path": str(target_path)}, context)
            result["syntax_check"] = syntax
        if bootstrap:
            result["repository_bootstrap"] = bootstrap
        return result


class ListWorkspaceDirectoryTool:
    """List files and directories inside the local workspace."""

    name = "list_workspace_directory"
    description = "List files and directories inside the local workspace."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        path_value = str(params.get("path") or params.get("directory_path") or params.get("local_path") or "").strip()
        include_hidden = bool(params.get("include_hidden", False))
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=1000,
            hard_max=2000,
        )

        try:
            target_path = _resolve_cwd(
                context.workspace_root,
                path_value,
                context=context,
                allow_repo_fallback=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if not target_path.exists():
            return {"error": "path does not exist"}
        if not target_path.is_dir():
            return {"error": "path is not a directory"}

        entries = []
        for child in sorted(target_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if not include_hidden and child.name.startswith("."):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "relative_path": str(child.relative_to(_workspace_root(context))),
                    "type": "directory" if child.is_dir() else "file",
                }
            )
            if len(entries) >= limit:
                break

        return {
            "path": str(target_path),
            "relative_path": str(target_path.relative_to(_workspace_root(context))),
            "entries": entries,
            "count": len(entries),
        }


class ReadWorkspaceFileTool:
    """Read a local file from the workspace."""

    name = "read_workspace_file"
    description = "Read a local file from the workspace."

    async def execute(self, params: dict, context: ToolContext) -> dict:
        path_value = str(params.get("path") or params.get("file_path") or "").strip()
        if not path_value:
            return {"error": "path is required"}

        max_chars = max(200, min(int(params.get("max_chars") or MAX_OUTPUT_CHARS), 50000))

        try:
            target_path = _resolve_cwd(
                context.workspace_root,
                path_value,
                context=context,
                allow_repo_fallback=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if not target_path.exists():
            return {"error": "path does not exist"}
        if not target_path.is_file():
            return {"error": "path is not a file"}

        try:
            content = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"error": "file is not valid UTF-8 text"}

        return {
            "path": str(target_path),
            "relative_path": str(target_path.relative_to(_workspace_root(context))),
            "content": content[:max_chars] + ("\\n...[truncated]" if len(content) > max_chars else ""),
            "size_bytes": target_path.stat().st_size,
        }


__all__ = [
    "ReadWorkspaceFileTool",
    "ListWorkspaceDirectoryTool",
    "WriteWorkspaceFileTool",
]
