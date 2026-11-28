"""Glob and grep tools for workspace files."""

from __future__ import annotations

import asyncio
import fnmatch
import re
from pathlib import Path
from typing import Any

from app.tools.context import ToolContext

from ._code_common import MAX_MATCHES, _resolve_workspace_path


def _resolve_search_root(raw_path: str, context: ToolContext) -> Path:
    requested_path = str(raw_path or "").strip() or "."
    return _resolve_workspace_path(
        requested_path,
        context.workspace_root,
        context=context,
        allow_repo_fallback=True,
    )


def _expand_brace_pattern(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", pattern)
    if not match:
        return [pattern]
    options = [part.strip() for part in match.group(1).split(",") if part.strip()]
    if not options:
        return [pattern]
    expanded: list[str] = []
    for option in options:
        expanded.extend(_expand_brace_pattern(pattern[: match.start()] + option + pattern[match.end() :]))
    return expanded


def _case_insensitive_matches(root: Path, pattern: str) -> list[Path]:
    lowered_pattern = pattern.lower()
    patterns = [lowered_pattern]
    if lowered_pattern.startswith("**/"):
        patterns.append(lowered_pattern[3:])

    matches: list[Path] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix().lower()
        if any(fnmatch.fnmatchcase(relative, item) for item in patterns):
            matches.append(candidate)
    return matches


def _glob_files(root: Path, pattern: str) -> list[Path]:
    matches: list[Path] = []
    seen: set[Path] = set()
    for expanded_pattern in _expand_brace_pattern(pattern):
        for match in root.glob(expanded_pattern):
            if match in seen:
                continue
            seen.add(match)
            matches.append(match)
    if matches or pattern == pattern.lower():
        return matches
    for match in _case_insensitive_matches(root, pattern):
        if match in seen:
            continue
        seen.add(match)
        matches.append(match)
    return matches


class GlobFilesTool:
    name = "glob_workspace_files"
    description = (
        "Find files in the workspace matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
        "Returns up to 100 results sorted by modification time (newest first). "
        "Use to locate files before reading or editing them."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pattern = str(params.get("pattern") or "").strip()
        raw_path = str(params.get("path") or "").strip()

        if not pattern:
            return {"error": "pattern is required"}

        try:
            search_root = _resolve_search_root(raw_path, context)
        except ValueError as exc:
            return {"error": str(exc)}

        if not search_root.exists():
            return {"error": f"Search path not found: {search_root}"}

        try:
            matches = _glob_files(search_root, pattern)
        except Exception as exc:
            return {"error": f"Glob error: {exc}"}

        matches.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

        truncated = len(matches) > MAX_MATCHES
        matches = matches[:MAX_MATCHES]
        files = [str(path) for path in matches if path.is_file()]

        return {
            "pattern": pattern,
            "root": str(search_root),
            "files": files,
            "count": len(files),
            "truncated": truncated,
        }


class GrepTool:
    name = "grep_workspace"
    description = (
        "Search file contents in the workspace using a regex pattern. "
        "Uses ripgrep (rg) if available, otherwise falls back to Python re. "
        "Returns up to 100 matches with file path, line number, and matched line. "
        "Use include to filter by file type (e.g. '*.py')."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        pattern = str(params.get("pattern") or "").strip()
        raw_path = str(params.get("path") or "").strip()
        include = str(params.get("include") or "").strip()
        case_insensitive = bool(params.get("case_insensitive", False))
        context_lines = int(params.get("context_lines") or 0)

        if not pattern:
            return {"error": "pattern is required"}

        try:
            search_root = _resolve_search_root(raw_path, context)
        except ValueError as exc:
            return {"error": str(exc)}
        if not search_root.exists():
            return {"error": f"Search path not found: {search_root}"}

        matches = await self._grep_rg(pattern, search_root, include, case_insensitive, context_lines)
        if matches is None:
            matches = self._grep_python(pattern, search_root, include, case_insensitive, context_lines)

        truncated = len(matches) > MAX_MATCHES
        matches = matches[:MAX_MATCHES]

        return {
            "pattern": pattern,
            "root": str(search_root),
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
        }

    async def _grep_rg(
        self,
        pattern: str,
        root: Path,
        include: str,
        case_insensitive: bool,
        context_lines: int = 0,
    ) -> list[dict[str, Any]] | None:
        cmd = ["rg", "--no-heading", "-nH", "--field-match-separator=|", "--regexp", pattern]
        if case_insensitive:
            cmd.append("-i")
        if context_lines > 0:
            cmd += ["-C", str(context_lines)]
        if include:
            cmd += ["--glob", include]
        cmd.append(str(root))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (TimeoutError, FileNotFoundError):
            return None
        except Exception:
            return None

        if proc.returncode == 2:
            return None

        results = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                file_path, lineno, content = parts
                results.append(
                    {
                        "file": file_path,
                        "line": int(lineno) if lineno.isdigit() else 0,
                        "content": content[:500],
                    }
                )
        return results

    def _grep_python(
        self,
        pattern: str,
        root: Path,
        include: str,
        case_insensitive: bool,
        context_lines: int = 0,
    ) -> list[dict[str, Any]]:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            return []

        include_pattern = (
            re.compile("^" + re.escape(include).replace(r"\*", ".*").replace(r"\?", ".") + "$") if include else None
        )

        results = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if include_pattern and not include_pattern.match(file_path.name):
                continue
            try:
                all_lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue

            for lineno, line in enumerate(all_lines, 1):
                if compiled.search(line):
                    if context_lines > 0:
                        start = max(0, lineno - 1 - context_lines)
                        end = min(len(all_lines), lineno + context_lines)
                        ctx = "\n".join(all_lines[start:end])
                        results.append(
                            {
                                "file": str(file_path),
                                "line": lineno,
                                "content": ctx[:1000],
                                "context_start_line": start + 1,
                            }
                        )
                    else:
                        results.append({"file": str(file_path), "line": lineno, "content": line[:500]})
                    if len(results) >= MAX_MATCHES * 2:
                        return results
        return results
