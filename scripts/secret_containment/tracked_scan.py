"""Dispatch tracked repository files to the matching secret containment scanner.

``git ls-files`` is the source of truth, so the check behaves the same in a
worktree, a clean clone, and a CI checkout, without network access.

Scope boundary, deliberately explicit:

* ``*.local.yaml`` / ``*.local.yml`` must never be tracked, anywhere in the tree.
  Matched on the literal name: the sanitized ``values.local.yaml.example`` is the
  guard that replaces the untracked original and must stay trackable.
* Release values files are checked wherever they appear, since a chart can live
  outside a ``deploy`` tree.
* Deployment env templates are checked inside deployment trees (any path with a
  ``deploy`` or ``deployment`` segment).
* Kubernetes Secret manifests are checked wherever they appear in a deployment tree,
  detected by ``kind: Secret`` content rather than by file name.
* Documentation copies (``*.env.example``, ``*.yaml.template``) are classified by
  ``file_kinds`` under their effective name, so a sanitized-looking suffix cannot
  carry material past the scanners.
* Application-level local development files outside deployment trees (for example
  the repository root ``.env.example``) are out of scope for this check; they are a
  separate concern outside deployment secret containment.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .contract import REASON_TRACKED_LOCAL_FILE, Finding
from .file_kinds import is_values_file, matches_any, scan_env_or_secret_path
from .values_scan import scan_values_path

# Local-only secret input: never tracked, regardless of location.
LOCAL_ONLY_VALUE_FILES = ("*.local.yaml", "*.local.yml")

# Path segments that mark a deployment tree.
DEPLOYMENT_SEGMENTS = ("deploy", "deployment")


def is_deployment_path(relative: str) -> bool:
    return any(part in DEPLOYMENT_SEGMENTS for part in Path(relative).parts[:-1])


def check_paths(root: Path, paths: list[str]) -> list[Finding]:
    """Run every applicable scanner over the given repository-relative paths."""
    findings: list[Finding] = []
    for relative in sorted(paths):
        name = Path(relative).name
        if matches_any(name, LOCAL_ONLY_VALUE_FILES):
            findings.append(Finding(relative, 0, "", REASON_TRACKED_LOCAL_FILE))
            continue
        absolute = root / relative
        if not absolute.is_file():
            continue
        if is_values_file(name):
            findings.extend(scan_values_path(root, relative))
            continue
        if not is_deployment_path(relative):
            continue
        findings.extend(scan_env_or_secret_path(relative, absolute))
    return findings


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [entry for entry in result.stdout.split("\0") if entry]
