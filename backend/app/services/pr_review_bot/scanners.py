"""Which scanners run on a pull request, and how the device calls them (tool runner)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from ..engineering_knowledge import stacks as stack_data

#: Licenses a shipped rule set may carry (opengrep with rules Octryx may pass on).
OSS_LICENSES = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "LGPL-2.1", "LGPL-2.1-only",
                          "LGPL-2.1-or-later"})
_SERVICES = Path(__file__).resolve().parent.parent


def scanners(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = stacks or stack_data.built_in()
    found: dict[str, dict[str, Any]] = {}
    rows = list(dict(data.get("general") or {}).get("scanners") or [])
    rows += [item for entry in dict(data.get("stacks") or {}).values() if isinstance(entry, dict)
             for item in entry.get("scanners") or []]
    for item in rows:
        if isinstance(item, dict) and item.get("id"):
            found[str(item["id"])] = dict(item)
    return list(found.values())


def _manifest_names(stacks: dict[str, Any] | None, entry: dict[str, Any]) -> set[str]:
    return {*stack_data.manifests(stacks), *(str(name) for name in entry.get("lock_files") or [])}


def selected(paths: list[str], stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not paths:
        return []
    names = {PurePosixPath(path).name for path in paths}
    return [entry for entry in scanners(stacks)
            if str(entry.get("when") or "always") != "manifests" or names & _manifest_names(stacks, entry)]


def command(entry: dict[str, Any], *, root: str, report: str, rules: str = "") -> list[str]:
    values = {"{root}": root, "{report}": report, "{rules}": rules}
    return [values.get(str(arg), str(arg)) for arg in entry.get("args") or []]


def rule_entries(entry: dict[str, Any]) -> tuple[list[tuple[str, bytes]], list[str]]:
    files: list[tuple[str, bytes]] = []
    notes: list[str] = []
    for source in entry.get("rule_sources") or []:
        source = dict(source or {})
        name, license_ = str(source.get("name") or "rules"), str(source.get("license") or "")
        if license_ not in OSS_LICENSES:
            notes.append(f"rule set {name} not shipped: license '{license_ or 'unknown'}' not cleared for Octryx")
            continue
        folder = (_SERVICES / str(source.get("path") or "")).resolve()
        if not folder.is_dir() or _SERVICES not in folder.parents:
            notes.append(f"rule set {name} not found")
            continue
        files += [(f"{name}/{path.relative_to(folder).as_posix()}", path.read_bytes())
                  for path in sorted(folder.rglob("*")) if path.is_file() and path.suffix in (".yaml", ".yml")]
    return files, notes


__all__ = ["OSS_LICENSES", "command", "rule_entries", "scanners", "selected"]
