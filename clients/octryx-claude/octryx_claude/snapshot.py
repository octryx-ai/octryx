"""Code intelligence in the launch folder: bind the git repository, upload HEAD.

``run_code_intelligence`` detects the repository of the launch folder, registers the
binding session -> Workspace -> repository (``POST /sessions/repository``) and, when
the Workspace allows local snapshots, uploads the tracked files at HEAD as a governed
repo@commit snapshot: the manifest names every blob, the platform answers which paths
it still wants (re-ingest is incremental by blob sha), the wanted contents follow in
bounded batches, and ``/complete`` closes the snapshot.

It never raises and never blocks the launch. It writes exactly one summary line with
fixed codes only; response bodies, tokens and raw remotes are never printed.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import httpx

from .platform import PlatformResult, SessionContext, call_control_plane, safe_code, valid_header_value
from .repository import (
    MAX_TREE_FILES,
    DetectionRefusal,
    RepositoryInfo,
    TreeFile,
    detect_repository,
    list_head_files,
    read_blobs,
)
from .state import LocalState

BIND_TIMEOUT = 15.0
MANIFEST_TIMEOUT = 30.0
FILES_TIMEOUT = 60.0
COMPLETE_TIMEOUT = 30.0
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 3 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
PREFIX = "octryx-claude: code intelligence: "
DIRTY_SUFFIX = "; working tree has uncommitted changes, HEAD was indexed"

_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


@dataclass(frozen=True)
class CodeIntelligenceOutcome:
    state: str  # off | snapshot_denied | snapshot_failed | indexed | incomplete
    summary: str
    code: str = ""


def _result_code(result: PlatformResult, step: str) -> str:
    return result.reason or result.state or f"{step}_{result.outcome}"


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def plan_batches(files: Iterable[TreeFile], *, max_files: int = MAX_BATCH_FILES,
                 max_bytes: int = MAX_BATCH_BYTES, max_file_bytes: int = MAX_FILE_BYTES) -> list[list[TreeFile]]:
    """Group files into upload batches of at most ``max_files`` and ``max_bytes`` raw bytes.

    A file larger than ``max_file_bytes`` is never sent (the manifest carried its size,
    so the platform has already listed it as skipped).
    """
    batches: list[list[TreeFile]] = []
    current: list[TreeFile] = []
    current_bytes = 0
    for item in files:
        if item.size > max_file_bytes:
            continue
        if current and (len(current) >= max_files or current_bytes + item.size > max_bytes):
            batches.append(current)
            current, current_bytes = [], 0
        current.append(item)
        current_bytes += item.size
    if current:
        batches.append(current)
    return batches


class _Run:
    """One code-intelligence pass for one session; every step returns an outcome."""

    def __init__(self, state: LocalState, context: SessionContext, http: httpx.Client) -> None:
        self.state = state
        self.context = context
        self.http = http

    def call(self, path: str, body: dict[str, Any], timeout: float) -> PlatformResult:
        return call_control_plane(
            self.state, self.context, "POST", f"/sessions/repository{path}",
            http=self.http, timeout=timeout, body=body,
        )

    def upload(self, repo: RepositoryInfo, wanted: list[TreeFile]) -> str:
        """Upload the wanted contents; returns ``""`` or the code of the first failure."""
        for batch in plan_batches(wanted):
            contents = read_blobs(repo.root, [item.blob_sha for item in batch])
            files = [
                {"path": item.path, "blob_sha": item.blob_sha,
                 "content_base64": base64.b64encode(contents[item.blob_sha]).decode("ascii")}
                for item in batch
                if item.blob_sha in contents and len(contents[item.blob_sha]) <= MAX_FILE_BYTES
            ]
            if not files:
                continue  # unreadable objects: /complete reports them as missing
            result = self.call("/files", {"head_commit": repo.head_commit, "files": files}, FILES_TIMEOUT)
            if result.outcome != "ok":
                return _result_code(result, "files")
        return ""


def _off(code: str) -> CodeIntelligenceOutcome:
    return CodeIntelligenceOutcome("off", f"{PREFIX}off ({code})", code)


def _bound_label(repo: RepositoryInfo, binding: dict[str, Any], context: SessionContext) -> str:
    name = str(binding.get("repository") or "")
    workspace = str(binding.get("workspace_id") or "")
    name = name if _DISPLAY_NAME.match(name) else "repository"
    workspace = workspace if valid_header_value(workspace) else context.workspace_id
    return f"{PREFIX}{name} @ {repo.head_commit[:7]} bound to Workspace {workspace}"


def _snapshot(run: _Run, repo: RepositoryInfo, label: str) -> CodeIntelligenceOutcome:
    dirty = DIRTY_SUFFIX if repo.head_dirty else ""
    listing = list_head_files(repo.root)
    if isinstance(listing, DetectionRefusal):
        return CodeIntelligenceOutcome("snapshot_failed", f"{label}; snapshot not uploaded ({listing.code})",
                                       listing.code)
    files = listing.files[:MAX_TREE_FILES]
    manifest = run.call("/manifest", {
        "head_commit": repo.head_commit,
        "files": [{"path": item.path, "blob_sha": item.blob_sha, "size": item.size} for item in files],
        "truncated": listing.truncated,
    }, MANIFEST_TIMEOUT)
    if manifest.outcome != "ok":
        code = _result_code(manifest, "manifest")
        return CodeIntelligenceOutcome("snapshot_failed", f"{label}; snapshot not uploaded ({code})", code)
    raw_wanted = manifest.body.get("wanted")
    wanted_paths = {path for path in raw_wanted if isinstance(path, str)} if isinstance(raw_wanted, list) else set()
    # Only paths of this manifest are ever read and sent.
    upload_error = run.upload(repo, [item for item in files if item.path in wanted_paths])
    # /complete runs after a failed batch too, so the platform records the snapshot as incomplete.
    complete = run.call("/complete", {"head_commit": repo.head_commit}, COMPLETE_TIMEOUT)
    if complete.outcome != "ok" or complete.state not in ("indexed", "incomplete"):
        code = upload_error or _result_code(complete, "complete")
        return CodeIntelligenceOutcome("snapshot_failed", f"{label}; snapshot not completed ({code})", code)
    indexed = _count(complete.body.get("files_indexed"))
    new = _count(complete.body.get("files_new"))
    if complete.state == "indexed" and not upload_error:
        return CodeIntelligenceOutcome("indexed", f"{label}, {indexed} files indexed ({new} new){dirty}")
    code = upload_error or "files_missing"
    missing = _count(complete.body.get("missing"))
    return CodeIntelligenceOutcome(
        "incomplete",
        f"{label}, snapshot incomplete ({code}): {indexed} files indexed ({new} new), {missing} missing{dirty}",
        code,
    )


def _code_intelligence(state: LocalState, context: SessionContext, cwd: Path | str,
                       http: httpx.Client) -> CodeIntelligenceOutcome:
    repo = detect_repository(cwd)
    if isinstance(repo, DetectionRefusal):
        return _off(repo.code)
    run = _Run(state, context, http)
    bound = run.call("", {
        "remote_url": repo.remote_url,
        "head_commit": repo.head_commit,
        "head_dirty": repo.head_dirty,
        "head_pushed": repo.head_pushed,
        "branch": repo.branch,
        # A confirmed change workflow may edit only inside this checkout.
        "root": str(Path(repo.root).absolute()),
    }, BIND_TIMEOUT)
    binding = bound.body.get("binding")
    if bound.outcome != "ok" or bound.state != "bound" or not isinstance(binding, dict):
        return _off(_result_code(bound, "bind"))
    label = _bound_label(repo, binding, context)
    snapshot = bound.body.get("snapshot") if isinstance(bound.body.get("snapshot"), dict) else {}
    if snapshot.get("state") != "allowed":
        reason = safe_code(snapshot.get("reason")) or "snapshot_not_allowed"
        return CodeIntelligenceOutcome(
            "snapshot_denied", f"{label}; local snapshots are not allowed in this Workspace ({reason})", reason
        )
    return _snapshot(run, repo, label)


def run_code_intelligence(state: LocalState, context: SessionContext, cwd: Path | str, *,
                          http: httpx.Client, out: TextIO) -> CodeIntelligenceOutcome:
    try:
        outcome = _code_intelligence(state, context, cwd, http)
    except Exception:  # noqa: BLE001 - code intelligence never blocks the launch
        outcome = _off("internal_error")
    try:
        out.write(outcome.summary + "\n")
        out.flush()
    except (OSError, ValueError):
        pass
    return outcome
