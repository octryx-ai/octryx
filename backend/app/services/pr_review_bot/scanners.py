"""Which scanners run on a pull request, and how the device calls them (tool runner).

The scanners are data (``stacks.json`` ``general.scanners`` plus a stack's own ``scanners``, the same id replaces):
each is a pinned launcher tool, its ``kind`` (:data:`.scan_findings.KINDS`), its ``args`` with the placeholders
``{root}`` (the unpacked changed files), ``{report}`` (the SARIF file it writes) and ``{rules}`` (the shipped rule
folder), and ``when`` it runs: ``always`` or ``manifests`` (only if a dependency manifest or lock file changed).

Rule sets travel as their own archive next to the files (``rule_entries``), never mixed into the scanned tree; each
``rule_sources`` entry names its license, and only sources whose license allows redistribution in an OSS product are
shipped (:data:`OSS_LICENSES`). Pure apart from reading the rule files of this package.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from ..engineering_knowledge import stacks as stack_data

#: Licenses a shipped rule set may carry (opengrep with rules Octryx may pass on).
OSS_LICENSES = frozenset({"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "LGPL-2.1", "LGPL-2.1-only",
                          "LGPL-2.1-or-later"})
_SERVICES = Path(__file__).resolve().parent.parent


def scanners(stacks: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every configured scanner, the general ones first; a stack's entry with the same id replaces it."""
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
    """The scanners for a pull request that changed ``paths`` (none when it changed no file)."""
    if not paths:
        return []
    names = {PurePosixPath(path).name for path in paths}
    return [entry for entry in scanners(stacks)
            if str(entry.get("when") or "always") != "manifests" or names & _manifest_names(stacks, entry)]


def command(entry: dict[str, Any], *, root: str, report: str, rules: str = "") -> list[str]:
    """The argument list after the tool, its placeholders filled; never through a shell."""
    values = {"{root}": root, "{report}": report, "{rules}": rules}
    return [values.get(str(arg), str(arg)) for arg in entry.get("args") or []]


def rule_entries(entry: dict[str, Any]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """The scanner's rule files as archive entries ``(source name/file, bytes)``, and a note per source left out
    (a license not in :data:`OSS_LICENSES`, or a path outside this installation's services)."""
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
