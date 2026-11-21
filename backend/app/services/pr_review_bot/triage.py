"""How to read a pull request: each changed file is

- **mechanical** (conservative: when in doubt, skim), as
  ``review.mechanical`` decides: renamed at 100 %, line endings only, whitespace only where it carries no meaning,
  Python with the same syntax tree and pragmas. The reviewer's diff leaves it out (``review_summarized_paths``; the
  evidence checks every path again) and lists it with the reason;
- **skim**: tests (the code style's ``test_globs``), excluded or generated files (its ``exclude``), lockfiles,
  translations, documentation (``*.md`` but a ``SPEC.md``);
- **read carefully**: everything else.

The **size brake**: more carefully read lines or files than the repository allows (``size_limit_lines`` /
``size_limit_files``, default 800 / 25) adds a note to the summary with a split into stacked pull requests by
folder. It never blocks and never changes the status.
"""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workflow_runs import safe_git

CAREFUL, SKIM, MECHANICAL = "careful", "skim", "mechanical"
LOCKFILES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock",
                       "Gemfile.lock", "composer.lock", "go.sum", "pubspec.lock", "Podfile.lock"})
L10N = ("*.arb", "**/locales/**", "**/i18n/**", "*.po", "*.pot", "**/l10n/**")
GENERATED = ("*.g.dart", "*.freezed.dart", "*.pb.go", "*_pb2.py", "*.min.js", "**/generated/**", "**/__generated__/**")


@dataclass(frozen=True, slots=True)
class FileTriage:
    path: str
    kind: str
    reason: str
    lines: int = 0  # added + removed
    old: str = ""  # the path it was renamed from

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "reason": self.reason, "lines": self.lines,
                **({"old": self.old} if self.old else {})}


def _matches(path: str, globs: list[str] | tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(path, glob.removeprefix("**/"))
               or fnmatch.fnmatch(Path(path).name, glob) for glob in globs)


def skim_reason(path: str, style: dict[str, Any]) -> str:
    """Why a file is only skimmed; ``''`` when it is read carefully. Pure."""
    general = dict(style.get("general") or {})
    name = Path(path).name
    if name in LOCKFILES:
        return "lockfile"
    if _matches(path, [str(item) for item in general.get("test_globs") or []] or
                ["tests/**", "test/**", "**/test_*.py", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]):
        return "test"
    excluded = [str(dict(row).get("glob") or "") for row in general.get("exclude") or [] if isinstance(row, dict)]
    if _matches(path, [glob for glob in excluded if glob]) or _matches(path, GENERATED):
        return "generated or excluded by the code style"
    if _matches(path, L10N):
        return "translations"
    if name.lower().endswith(".md") and name != "SPEC.md":
        return "documentation"
    return ""


async def classify(root: str, base: str, head: str, style: dict[str, Any]) -> list[FileTriage]:
    """Every file the pull request changes with how to read it (renames detected)."""
    code, out, _err = await safe_git.git(root, *safe_git.DIFF, "--numstat", "-M", "-z", base, head)
    if code != 0:
        return []
    found: list[FileTriage] = []
    records = out.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        parts = record.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        old = ""
        if not path:  # a rename: the old and the new path follow as their own records
            old, path = records[index], records[index + 1]
            index += 2
        lines = (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
        found.append(await _one(root, base, head, old, path, lines, style))
    return found


async def _one(root: str, base: str, head: str, old: str, path: str, lines: int,
               style: dict[str, Any]) -> FileTriage:
    from ..workflow_runs.review.mechanical import mechanical_reason

    reason = await mechanical_reason(root, base, path, old=old, head=head)
    if reason:
        return FileTriage(path, MECHANICAL, reason, lines, old)
    reason = skim_reason(path, style)
    return FileTriage(path, SKIM, reason, lines, old) if reason else FileTriage(path, CAREFUL, "", lines, old)


def split(files: list[FileTriage], limit_lines: int, limit_files: int) -> list[tuple[str, list[FileTriage]]]:
    """Groups of carefully read files within the limits: by folder, one level deeper while a folder is still too large,
    and a folder that cannot be split further in batches of files (``name (1/3)``). Pure."""
    def fits(items: list[FileTriage]) -> bool:
        return len(items) <= limit_files and sum(item.lines for item in items) <= limit_lines

    def folder(item: FileTriage, depth: int) -> str:
        parts = Path(item.path).parts[:-1]
        return "/".join(parts[:depth]) + "/" if parts else "./"

    def batches(name: str, items: list[FileTriage]) -> list[tuple[str, list[FileTriage]]]:
        out: list[list[FileTriage]] = [[]]
        for item in sorted(items, key=lambda entry: entry.path):
            if out[-1] and not fits([*out[-1], item]):
                out.append([])
            out[-1].append(item)
        if len(out) == 1:
            return [(name, out[0])]
        return [(f"{name} ({index}/{len(out)})", group) for index, group in enumerate(out, 1)]

    def by_folder(items: list[FileTriage], depth: int) -> list[tuple[str, list[FileTriage]]]:
        groups: dict[str, list[FileTriage]] = defaultdict(list)
        for item in items:
            groups[folder(item, depth)].append(item)
        out: list[tuple[str, list[FileTriage]]] = []
        for name, group in sorted(groups.items()):
            deeper = max(len(Path(item.path).parts) - 1 for item in group) > depth
            if fits(group):
                out.append((name, group))
            elif deeper:  # one level down, also through a single subfolder: batches carry the deepest name
                out += by_folder(group, depth + 1)
            else:
                out += batches(name, group)
        return out

    return by_folder(files, 1)


def size_note(files: list[FileTriage], limit_lines: int, limit_files: int) -> str:
    """The size brake's note with a split into stacked pull requests; ``''`` within the limits. Pure."""
    careful = [item for item in files if item.kind == CAREFUL]
    lines = sum(item.lines for item in careful)
    if lines <= limit_lines and len(careful) <= limit_files:
        return ""
    groups = split(careful, limit_lines, limit_files)
    rows = [f"{index}. `{name}` ({len(items)} file(s), {sum(item.lines for item in items)} lines"
            + (f": {Path(items[0].path).name} … {Path(items[-1].path).name}" if len(items) > 1 else "") + ")"
            for index, (name, items) in enumerate(groups, 1)]
    return (f"**Large pull request:** {len(careful)} file(s) and {lines} changed lines to read carefully (this "
            f"repository suggests at most {limit_files} files / {limit_lines} lines). Consider splitting it into "
            f"{len(groups)} stacked pull requests, for example:\n" + "\n".join(rows[:10]))


def reading_section(files: list[FileTriage]) -> str:
    """The reviewer's guide: what to read carefully, what to skim, what the platform left out. Pure."""
    def listed(kind: str, with_reason: bool) -> list[str]:
        rows = [f"  {item.path}" + (f" ({item.reason})" if with_reason else "") for item in files if item.kind == kind]
        return rows or ["  (none)"]

    return "\n".join(["Read carefully first:", *listed(CAREFUL, False), "Skim (only obvious problems):",
                      *listed(SKIM, True), "Left out of the diff as mechanical (verified by the platform):",
                      *listed(MECHANICAL, True)])


__all__ = ["CAREFUL", "MECHANICAL", "SKIM", "FileTriage", "classify", "reading_section", "size_note", "skim_reason",
           "split"]
