"""The official formatter and linter of each language, run by the platform itself (code style step
iv): ``dart format`` / ``flutter analyze``, ``ruff format`` / ``ruff check``, ``prettier`` / ``eslint``, ``gofmt`` /
``go vet``, ``cargo fmt`` / ``cargo clippy``, google-java-format (or Spotless) / Checkstyle, ktlint / detekt, as the
resolved style names them (``code_style.languages.<language>.formatter|linter``), whatever the
engine's own environment file declares. The repository's own configuration wins (``config_files``, then
``repo_config_command``). A tool that is not installed is reported ``missing`` (the platform turns it red, never a
silent pass). Runs outside the agent's sandbox, in the package folder of the files (nearest ``pubspec.yaml`` /
``package.json`` / ``go.mod``), with a timeout; the server judges the results (``code_style.check.tool_findings``)."""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

FORMAT_TIMEOUT = 30
LINT_TIMEOUT = 120
# The Stop hook has 240 s in all (run_contract.STOP_HOOK_TIMEOUT): tools left over then are skipped there and
# judged by the pipeline, which runs them on the whole change.
BUDGET_SECONDS = 170
MAX_OUTPUT = 2000
EXTENSIONS = {".dart": "dart", ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
              ".jsx": "javascript", ".mjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
              ".kts": "kotlin"}
_BUILD = ("pom.xml", "build.gradle", "build.gradle.kts")
PACKAGE_MARKERS = {"dart": ("pubspec.yaml",), "typescript": ("package.json",), "javascript": ("package.json",),
                   "go": ("go.mod",), "rust": ("Cargo.toml",), "java": _BUILD, "kotlin": _BUILD}
PLATFORM_ESLINT = ".octryx-eslint.config.mjs"
ESLINT_CONFIG = ('import js from "@eslint/js";\nimport tseslint from "typescript-eslint";\n'
                 "export default tseslint.config(js.configs.recommended, ...tseslint.configs.recommended);\n")


def _language(path: str) -> str | None:
    return next((language for suffix, language in EXTENSIONS.items() if path.lower().endswith(suffix)), None)


APP_MARKER = ".octryx/environment.json"  # the run's app folder: where the agent and the pipeline work


def _package(root: Path, path: str, language: str) -> Path:
    """Where the language's tools run for ``path``: the nearest folder with a package marker of the language or the
    app's environment file, else the repository: run from the repository root, ruff would count the app's own
    package as third-party and give another verdict (I001) than the agent's run in the app folder."""
    markers = (*PACKAGE_MARKERS.get(language, ()), APP_MARKER)
    folder = (root / path).parent
    while folder != root and root in folder.parents:
        if any((folder / marker).is_file() for marker in markers):
            return folder
        folder = folder.parent
    return root


def _has_config(folder: Path, root: Path, patterns: list[str]) -> bool:
    for pattern in patterns:
        name, _, section = pattern.partition(":")
        for place in {folder, root}:
            for candidate in place.glob(name):
                try:
                    if not section or section in candidate.read_text(errors="replace"):
                        return True
                except OSError:
                    continue
    return False


def _excluded(path: str, rules: dict[str, Any]) -> bool:
    globs = [str(row.get("glob")) for row in rules.get("exclude") or [] if isinstance(row, dict)]
    return any(fnmatch(path, glob) or fnmatch(path, glob.replace("**/", "")) for glob in globs)


def _env(root: Path, folder: Path) -> dict[str, str]:
    extra = [str(place) for place in (folder / "node_modules" / ".bin", root / "node_modules" / ".bin",
                                      root / ".venv" / "bin", folder / ".venv" / "bin") if place.is_dir()]
    return {**os.environ, "PATH": os.pathsep.join([*extra, os.environ.get("PATH", "")])}


def _run(kind: str, language: str, tool: dict[str, Any], folder: Path, root: Path, files: list[str]) -> dict[str, Any]:
    # The build's own setup first (Spotless / Checkstyle / detekt in Gradle or Maven), then the repository's config.
    variant = next((item for item in tool.get("variants") or []
                    if _has_config(folder, root, [str(glob) for glob in item.get("when") or []])), None)
    own = variant is not None or _has_config(folder, root, [str(item) for item in tool.get("config_files") or []])
    template = str((variant or {}).get("command") or (tool.get("repo_config_command") if own else None)
                   or tool.get("command") or "")
    relative = [os.path.relpath(root / name, folder) for name in files]
    command = shlex.split(template.replace("{files}", "").replace("{platform_config}", PLATFORM_ESLINT))
    if "{files}" in template:
        command += relative
    name = command[0] if command else ""
    shown = template.replace(" {files}", "").replace("{files}", "").replace("{platform_config}", PLATFORM_ESLINT)
    result = {"language": language, "kind": kind, "tool": name, "config": "repo" if own else "platform",
              "folder": os.path.relpath(folder, root), "os": platform.system(),  # the install hint fits the OS
              "command": shown.strip()[:200]}  # what the platform ran, for the agent to run the same
    env = _env(root, folder)
    local = "/" in name and os.access(folder / name, os.X_OK)  # ./gradlew, ./mvnw in the package folder
    if not name or (not local and shutil.which(name, path=env["PATH"]) is None):
        return {**result, "state": "missing"}
    written = folder / PLATFORM_ESLINT if "{platform_config}" in template else None
    try:
        if written is not None:
            written.write_text(ESLINT_CONFIG)
        done = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True,
                              timeout=FORMAT_TIMEOUT if kind == "formatter" else LINT_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {**result, "state": "timeout"}
    except OSError as error:
        return {**result, "state": "missing", "output": str(error)[:200]}
    finally:
        if written is not None:
            written.unlink(missing_ok=True)
    output = (done.stdout + done.stderr).strip()
    # gofmt -l exits 0 and lists the files it would change.
    failed = done.returncode != 0 or (name == "gofmt" and bool(done.stdout.strip()))
    return {**result, "state": "failed" if failed else "ok", **({"output": output[-MAX_OUTPUT:]} if failed else {})}


_LOCATION = re.compile(r"(?P<path>[\w./-]+\.(?:py|dart|ts|tsx|js|jsx|mjs|go|rs|java|kt|kts)):(?P<line>\d+)")
BASE_PREFIX = ".octryx-base-"


def _git_text(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30,
                              check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _added_lines(root: Path, base: str, names: list[str]) -> dict[str, set[int]]:
    from .contract_sizes import _added_lines as parse  # noqa: PLC0415

    diff = _git_text(root, "diff", "-U0", "--no-color", "--no-ext-diff", base, "--", *names)
    return parse(diff) if diff else {}


def _old_formatting(kind: str, language: str, tool: dict[str, Any], folder: Path, root: Path, name: str,
                    before: str) -> bool:
    """Whether the formatter rejects the file's content at the base too (checked on a copy next to it)."""
    copy = (root / name).with_name(BASE_PREFIX + (root / name).name)
    try:
        copy.write_text(before)
        return _run(kind, language, tool, folder, root, [os.path.relpath(copy, root)]).get("state") == "failed"
    except OSError:
        return False
    finally:
        copy.unlink(missing_ok=True)


def _old_debt(result: dict[str, Any], kind: str, language: str, tool: dict[str, Any], folder: Path, root: Path,
              names: list[str], base: str) -> bool:
    """Whether a red tool result is only the files' state before the change (findings on lines the change did not
    touch must not hold the change red). A linter: every finding it locates is on
    a line the change did not add, in a file that existed. A formatter: each file it rejects alone was rejected at
    the base too. Unlocatable output stays the change's."""
    befores = {name: _git_text(root, "cat-file", "-p", f"{base}:{name}") for name in names}
    if kind == "linter":
        added = _added_lines(root, base, names)
        found = []
        for match in _LOCATION.finditer(str(result.get("output") or "")):
            path = match["path"]
            relative = os.path.relpath(path, root) if path.startswith("/") else os.path.normpath(
                os.path.join(os.path.relpath(folder, root), path))
            found.append((relative, int(match["line"])))
        return bool(found) and all(befores.get(path) is not None and line not in added.get(path, set())
                                   for path, line in found)
    rejected = [name for name in names if _run(kind, language, tool, folder, root, [name]).get("state") == "failed"]
    return bool(rejected) and all(befores.get(name) is not None and _old_formatting(
        kind, language, tool, folder, root, name, str(befores[name])) for name in rejected)


def _split_linter(result: dict[str, Any], folder: Path, root: Path, names: list[str],
                  base: str) -> list[dict[str, Any]]:
    """A red linter result split by finding: each output line that names a
    place goes to the change (a line it added, or a new file) or to the old debt (a line the file already had).

    Before, one finding on an added line made the whole output the change's, and the agent got 40 old long lines of
    system_test/run_system_test.py with its own one and fixed them all. Now the change's result carries only its own
    lines; the older ones come as a second result marked ``old_debt`` (the server warns). Output without any place
    stays the change's."""
    befores = {name: _git_text(root, "cat-file", "-p", f"{base}:{name}") for name in names}
    added = _added_lines(root, base, names)

    def is_old(match: re.Match) -> bool:
        path = match["path"]
        relative = os.path.relpath(path, root) if path.startswith("/") else os.path.normpath(
            os.path.join(os.path.relpath(folder, root), path))
        return befores.get(relative) is not None and int(match["line"]) not in added.get(relative, set())

    new: list[str] = []
    old: list[str] = []
    # A finding is a block (ruff's default: the rule, `--> file:line`, the code) or a line (ruff concise, flutter
    # analyze, go vet): a block with one place goes whole to one side; a block of many places is split by line.
    for block in re.split(r"\n\s*\n", str(result.get("output") or "")):
        located = [(line, match) for line in block.splitlines() if (match := _LOCATION.search(line))]
        if len({(match["path"], match["line"]) for _line, match in located}) == 1:
            (old if is_old(located[0][1]) else new).append(block.strip("\n"))
            continue
        for line, match in located:
            (old if is_old(match) else new).append(line)
    if not new and not old:
        return [result]
    if not new:
        return [{**result, "old_debt": True}]
    if not old:
        return [result]
    return [{**result, "output": "\n\n".join(new)[-MAX_OUTPUT:]},
            {**result, "output": "\n\n".join(old)[-MAX_OUTPUT:], "old_debt": True}]


def run_tools(root: Path, style: dict[str, Any], files: list[str], *,
              budget: float = BUDGET_SECONDS, base: str = "") -> list[dict[str, Any]]:
    """The formatter and linter results for the changed ``files`` (repository-relative), per language and package;
    a tool whose turn comes after ``budget`` seconds is ``skipped``. With ``base`` a red result that is only the
    files' state before the change is marked ``old_debt`` (the server warns instead of blocking)."""
    started = time.monotonic()
    groups: dict[tuple[str, Path], list[str]] = {}
    for name in files:
        language = _language(name)
        rules = dict(dict(style.get("languages") or {}).get(language) or {}) if language else {}
        if language and rules and not _excluded(name, rules):
            groups.setdefault((language, _package(root, name, language)), []).append(name)
    results = []
    for (language, folder), names in sorted(groups.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        rules = dict(style["languages"][language])
        for kind in ("formatter", "linter"):
            tool = dict(rules.get(kind) or {})
            if tool.get("enabled") is False or not tool.get("command"):
                continue
            if time.monotonic() - started > budget:
                results.append({"language": language, "kind": kind, "state": "skipped",
                                "folder": os.path.relpath(folder, root)})
                continue
            result = _run(kind, language, tool, folder, root, names)
            judged = base and result.get("state") == "failed" and time.monotonic() - started <= budget
            if judged and kind == "linter":
                results.extend(_split_linter(result, folder, root, names, base))
                continue
            if judged and _old_debt(result, kind, language, tool, folder, root, names, base):
                result["old_debt"] = True
            results.append(result)
    return results


__all__ = ["PLATFORM_ESLINT", "run_tools"]
