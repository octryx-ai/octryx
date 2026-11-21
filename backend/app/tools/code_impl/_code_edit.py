"""Edit tools and edit-strategy helpers for workspace files."""

from __future__ import annotations

import difflib
import re
import textwrap
from time import perf_counter
from typing import Any

from app.tools.context import ToolContext

from ..runtime_impl._runtime_execution_events import build_execution_event
from ..runtime_impl._runtime_policy import evaluate_workspace_mutation_policy
from ._code_common import _ensure_repository_for_write, _resolve_workspace_path
from ._code_edit_preview import apply_all, proposed_content
from ._code_syntax import CheckFileSyntaxTool


def _exact_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    if old not in content:
        return None
    if replace_all:
        return content.replace(old, new)
    return content.replace(old, new, 1)


def _line_trimmed_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Match after trimming each line individually."""
    old_trimmed = "\n".join(line.strip() for line in old.splitlines())
    content_lines = content.splitlines(keepends=True)
    content_trimmed_lines = [line.rstrip("\r\n").strip() for line in content_lines]
    content_trimmed = "\n".join(content_trimmed_lines)

    if old_trimmed not in content_trimmed:
        return None

    start = content_trimmed.find(old_trimmed)
    if start == -1:
        return None

    trimmed_before = content_trimmed[:start]
    line_offset = trimmed_before.count("\n")
    match_lines = old_trimmed.count("\n") + 1

    orig_start = sum(len(content_lines[index]) for index in range(line_offset))
    orig_end = sum(len(content_lines[index]) for index in range(line_offset + match_lines))

    result = content[:orig_start] + new + content[orig_end:]
    if not replace_all:
        return result
    return content.replace(content[orig_start:orig_end], new)


def _whitespace_normalized_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Normalize runs of whitespace before matching."""
    norm_old = re.sub(r"\s+", " ", old).strip()
    norm_content = re.sub(r"\s+", " ", content).strip()
    if norm_old not in norm_content:
        return None

    old_words = norm_old.split()
    if not old_words:
        return None

    pattern = r"\s+".join(re.escape(word) for word in old_words)
    flags = re.MULTILINE
    if replace_all:
        return re.sub(pattern, lambda _: new, content, flags=flags)
    match = re.search(pattern, content, flags=flags)
    if not match:
        return None
    return content[: match.start()] + new + content[match.end() :]


def _indentation_flexible_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Match ignoring leading indentation prefix on every line."""
    old_lines = old.splitlines()
    if not old_lines:
        return None
    dedented = textwrap.dedent(old)
    if dedented == old:
        return None
    if dedented not in content:
        return None
    if replace_all:
        return content.replace(dedented, new)
    return content.replace(dedented, new, 1)


def _escape_normalized_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Unescape \\n, \\t etc. in old_string before matching."""
    unescaped = old.encode("raw_unicode_escape").decode("unicode_escape")
    if unescaped == old:
        return None
    if unescaped not in content:
        return None
    if replace_all:
        return content.replace(unescaped, new)
    return content.replace(unescaped, new, 1)


def _block_anchor_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Use first and last lines of old_string as anchors; accept fuzzy middle lines."""
    old_lines = old.splitlines()
    if len(old_lines) < 3:
        return None
    first_line = old_lines[0].strip()
    last_line = old_lines[-1].strip()
    content_lines = content.splitlines(keepends=True)
    block_len = len(old_lines)
    for index, line in enumerate(content_lines):
        if line.rstrip("\r\n").strip() != first_line:
            continue
        if index + block_len - 1 >= len(content_lines):
            continue
        if content_lines[index + block_len - 1].rstrip("\r\n").strip() != last_line:
            continue
        block = "".join(content_lines[index : index + block_len])
        ratio = difflib.SequenceMatcher(None, old, block).ratio()
        if ratio < 0.6:
            continue
        orig_start = sum(len(content_lines[pos]) for pos in range(index))
        orig_end = orig_start + len(block)
        result = content[:orig_start] + new + content[orig_end:]
        if replace_all:
            return result
        return result
    return None


def _trimmed_boundary_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Trim only leading whitespace of first line and trailing whitespace of last line."""
    old_lines = old.splitlines(keepends=True)
    if not old_lines:
        return None
    adjusted_first = old_lines[0].lstrip()
    adjusted_last = old_lines[-1].rstrip() if len(old_lines) > 1 else old_lines[0].strip()
    if len(old_lines) == 1:
        adjusted = adjusted_first.rstrip()
    else:
        adjusted = adjusted_first + "".join(old_lines[1:-1]) + adjusted_last
    if adjusted == old or adjusted not in content:
        return None
    if replace_all:
        return content.replace(adjusted, new)
    return content.replace(adjusted, new, 1)


def _context_aware_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """Find the best-matching position using the middle line as a unique anchor."""
    old_lines = old.splitlines()
    if len(old_lines) < 2:
        return None
    mid_idx = len(old_lines) // 2
    mid_line = old_lines[mid_idx].strip()
    if not mid_line:
        return None

    content_lines = content.splitlines(keepends=True)
    block_len = len(old_lines)
    candidates: list[tuple[float, int, str]] = []
    for index, line in enumerate(content_lines):
        if line.rstrip("\r\n").strip() != mid_line:
            continue
        start_i = index - mid_idx
        if start_i < 0 or start_i + block_len > len(content_lines):
            continue
        block = "".join(content_lines[start_i : start_i + block_len])
        ratio = difflib.SequenceMatcher(None, old, block).ratio()
        candidates.append((ratio, start_i, block))

    if not candidates:
        return None
    candidates.sort(key=lambda entry: -entry[0])
    best_ratio, best_start, best_block = candidates[0]
    if best_ratio < 0.7:
        return None
    orig_start = sum(len(content_lines[pos]) for pos in range(best_start))
    orig_end = orig_start + len(best_block)
    return content[:orig_start] + new + content[orig_end:]


def _multi_occurrence_replace(content: str, old: str, new: str, replace_all: bool) -> str | None:
    """When old_string occurs multiple times, pick the first occurrence."""
    occurrences = []
    start = 0
    while True:
        pos = content.find(old, start)
        if pos == -1:
            break
        occurrences.append(pos)
        start = pos + 1
    if len(occurrences) < 2:
        return None
    if replace_all:
        return content.replace(old, new)
    pos = occurrences[0]
    return content[:pos] + new + content[pos + len(old) :]


_REPLACERS = [
    _exact_replace,
    _line_trimmed_replace,
    _whitespace_normalized_replace,
    _indentation_flexible_replace,
    _escape_normalized_replace,
    _block_anchor_replace,
    _trimmed_boundary_replace,
    _context_aware_replace,
    _multi_occurrence_replace,
]


def _apply_edit(content: str, old_string: str, new_string: str, replace_all: bool) -> tuple[str, str]:
    """Try each replacer in order. Returns (new_content, strategy_used)."""
    for replacer in _REPLACERS:
        try:
            result = replacer(content, old_string, new_string, replace_all)
            if result is not None and result != content:
                return result, replacer.__name__
        except Exception:
            continue
    raise ValueError(
        f"old_string not found in file (tried {len(_REPLACERS)} strategies). "
        "Check that old_string exactly matches the content to replace."
    )


class EditFileTool:
    name = "edit_workspace_file"
    description = (
        "Make a targeted find-and-replace edit to a file in the workspace. "
        "Prefer this over write_workspace_file for partial changes. "
        "old_string must uniquely identify the text to replace. "
        "Uses 9 fallback matching strategies (exact → line-trimmed → whitespace-normalized → "
        "indentation-flexible → escape-normalized → block-anchor → trimmed-boundary → "
        "context-aware → multi-occurrence)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or params.get("file_path") or "").strip()
        old_string = params.get("old_string", "")
        new_string = params.get("new_string", "")
        replace_all = bool(params.get("replace_all", False))

        if not raw_path:
            return {"error": "path is required"}
        if old_string == new_string:
            return {"error": "old_string and new_string must differ"}

        started_at = perf_counter()
        bootstrap = await _ensure_repository_for_write(context)
        if bootstrap and bootstrap.get("status") == "error":
            return {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap}
        file_path = _resolve_workspace_path(
            raw_path,
            context.workspace_root,
            context=context,
            allow_repo_fallback=True,
            allow_missing=True,
        )

        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}
        if not file_path.is_file():
            return {"error": f"Not a file: {file_path}"}

        # The content the edit leaves goes with the decision (a phase's formatting-only rule reads it).
        proposed = proposed_content(file_path, lambda text: _apply_edit(text, old_string, new_string, replace_all)[0])
        policy_decision = await evaluate_workspace_mutation_policy(
            context, tool_name=self.name, target_paths=[file_path], proposed=proposed)
        if policy_decision.get("blocking"):
            return {
                "error": policy_decision["reason"],
                "path": str(file_path),
                "coding_policy_decision": policy_decision,
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "coding_policy_decision": policy_decision},
                ),
            }

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return {"error": f"Cannot read file: {exc}"}

        try:
            new_content, strategy = _apply_edit(content, old_string, new_string, replace_all)
        except ValueError as exc:
            return {
                "error": str(exc),
                "path": str(file_path),
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "replace_all": replace_all},
                ),
            }

        try:
            file_path.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return {
                "error": f"Cannot write file: {exc}",
                "path": str(file_path),
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "replace_all": replace_all},
                ),
            }

        line_delta = new_content.count("\n") - content.count("\n")
        diff_lines = list(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{file_path.name}",
                tofile=f"b/{file_path.name}",
                n=3,
            )
        )
        diff_text = "".join(diff_lines[:200])
        result: dict[str, Any] = {
            "path": str(file_path),
            "strategy": strategy,
            "replace_all": replace_all,
            "lines_delta": line_delta,
            "status": "edited",
            "diff": diff_text,
            "coding_policy_decision": policy_decision,
            "execution_event": build_execution_event(
                kind="edit",
                tool_name=self.name,
                command=f"edit {raw_path}",
                cwd=str(file_path.parent),
                status="succeeded",
                exit_code=0,
                duration_ms=int((perf_counter() - started_at) * 1000),
                stdout=diff_text,
                metadata={
                    "path": str(file_path),
                    "strategy": strategy,
                    "replace_all": replace_all,
                    "lines_delta": line_delta,
                },
            ),
        }
        if params.get("auto_check"):
            syntax = await CheckFileSyntaxTool().execute({"path": str(file_path)}, context)
            result["syntax_check"] = syntax
        if bootstrap:
            result["repository_bootstrap"] = bootstrap
        return result


class MultiEditFileTool:
    name = "multi_edit_workspace_file"
    description = (
        "Apply multiple sequential find-and-replace edits to a single file in one call. "
        "Each edit is applied in order; later edits see the result of earlier ones. "
        "Use when you need to make several independent changes to the same file."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or params.get("file_path") or "").strip()
        edits = params.get("edits") or []

        if not raw_path:
            return {"error": "path is required"}
        if not edits:
            return {"error": "edits list is required and must not be empty"}

        started_at = perf_counter()
        bootstrap = await _ensure_repository_for_write(context)
        if bootstrap and bootstrap.get("status") == "error":
            return {"error": "Repository bootstrap failed", "repository_bootstrap": bootstrap}
        file_path = _resolve_workspace_path(
            raw_path,
            context.workspace_root,
            context=context,
            allow_repo_fallback=True,
            allow_missing=True,
        )

        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}

        policy_decision = await evaluate_workspace_mutation_policy(
            context, tool_name=self.name, target_paths=[file_path],
            proposed=proposed_content(file_path, lambda text: apply_all(text, edits, _apply_edit)))
        if policy_decision.get("blocking"):
            return {
                "error": policy_decision["reason"],
                "path": str(file_path),
                "coding_policy_decision": policy_decision,
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"multi-edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "coding_policy_decision": policy_decision},
                ),
            }

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            return {"error": f"Cannot read file: {exc}"}

        applied = []
        for index, edit in enumerate(edits):
            old_string = edit.get("old_string", "")
            new_string = edit.get("new_string", "")
            replace_all = bool(edit.get("replace_all", False))
            if old_string == new_string:
                applied.append({"index": index, "status": "skipped", "reason": "old_string == new_string"})
                continue
            try:
                content, strategy = _apply_edit(content, old_string, new_string, replace_all)
                applied.append({"index": index, "status": "applied", "strategy": strategy})
            except ValueError as exc:
                applied.append({"index": index, "status": "error", "reason": str(exc)})
                break

        errors = [result for result in applied if result["status"] == "error"]
        if errors:
            return {
                "error": f"Edit {errors[0]['index']} failed: {errors[0]['reason']}",
                "applied": applied,
                "path": str(file_path),
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"multi-edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "edits_requested": len(edits), "results": applied},
                ),
            }

        try:
            file_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return {
                "error": f"Cannot write file: {exc}",
                "path": str(file_path),
                "execution_event": build_execution_event(
                    kind="edit",
                    tool_name=self.name,
                    command=f"multi-edit {raw_path}",
                    cwd=str(file_path.parent),
                    status="failed",
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    metadata={"path": str(file_path), "edits_requested": len(edits), "results": applied},
                ),
            }

        result = {
            "path": str(file_path),
            "edits_applied": len([entry for entry in applied if entry["status"] == "applied"]),
            "results": applied,
            "coding_policy_decision": policy_decision,
            "execution_event": build_execution_event(
                kind="edit",
                tool_name=self.name,
                command=f"multi-edit {raw_path}",
                cwd=str(file_path.parent),
                status="succeeded",
                exit_code=0,
                duration_ms=int((perf_counter() - started_at) * 1000),
                metadata={
                    "path": str(file_path),
                    "edits_requested": len(edits),
                    "edits_applied": len([entry for entry in applied if entry["status"] == "applied"]),
                    "results": applied,
                },
            ),
        }
        if bootstrap:
            result["repository_bootstrap"] = bootstrap
        return result
