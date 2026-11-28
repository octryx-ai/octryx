"""A workflow run's work in progress, pushed to ``octryx-wip/<run id>`` and restored by the next runtime.
Pushes are always fast-forwards; a restore never overwrites a folder's own uncommitted changes."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .work_state import WorkStateError, capture_work_state, git, push_branch, repository_root, safe_segment

PREFIX = "octryx-wip"
AUTHOR = ("octryx-claude", "octryx-claude@octryx.invalid")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def wip_branch(run_id: str) -> str:
    return f"{PREFIX}/{safe_segment(run_id)}"


def _local_ref(run_id: str) -> str:
    return f"refs/octryx-wip/{safe_segment(run_id)}"


def _fetch(root: Path, remote: str, run_id: str) -> str:
    git(root, "fetch", "--no-tags", "--quiet", remote, f"+refs/heads/{wip_branch(run_id)}:{_local_ref(run_id)}",
        check=False)
    sha = git(root, "rev-parse", "--verify", "--quiet", _local_ref(run_id), check=False)
    return sha if _SHA.match(sha) else ""


def push_run_wip(folder: str, run_id: str, trailer: str = "") -> dict[str, Any]:
    message = f"WIP of workflow run {run_id}" + (f"\n\n{trailer.strip()}" if trailer.strip() else "")
    branch = wip_branch(run_id)
    root = repository_root(folder)
    if root is None or not run_id:
        return {"state": "failed", "branch": branch, "reason": "no_repository"}
    try:
        state = capture_work_state(root, user_name=AUTHOR[0], user_email=AUTHOR[1],
                                   message=message)
        if not state.remote_name:
            return {"state": "failed", "branch": branch, "reason": "no_remote"}
        previous = _fetch(root, state.remote_name, run_id)
        commit = state.wip_commit
        if previous:
            tree = git(root, "rev-parse", f"{commit}^{{tree}}")
            if tree == git(root, "rev-parse", f"{previous}^{{tree}}"):
                return {"state": "unchanged", "branch": branch, "sha": previous}
            author = {"GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1],
                      "GIT_COMMITTER_NAME": AUTHOR[0], "GIT_COMMITTER_EMAIL": AUTHOR[1]}
            commit = git(root, "commit-tree", "--no-gpg-sign", tree, "-p", previous, "-p", state.wip_commit,
                         "-m", message, extra_env=author)
        git(root, "update-ref", f"refs/heads/{branch}", commit)  # this module's own namespace only
        if not push_branch(state, branch):
            return {"state": "failed", "branch": branch, "reason": "push_refused"}
        return {"state": "pushed", "branch": branch, "sha": commit}
    except WorkStateError as error:
        return {"state": "failed", "branch": branch, "reason": str(error) or "git_failed"}


def _names(root: Path, older: str, newer: str) -> set[str]:
    listed = git(root, "diff", "--name-only", "-z", "--no-renames", older, newer, check=False)
    return {name for name in listed.split("\0") if name}


def restore_run_wip(root: Path, run_id: str) -> dict[str, Any]:
    # Checking out the whole WIP tree would drop files merged since, and the next git add -A would delete them.
    branch = wip_branch(run_id)
    try:
        remote = "origin" if "origin" in git(root, "remote", check=False).split() else ""
        sha = _fetch(root, remote, run_id) if remote and run_id else ""
        if not sha:
            return {"state": "absent", "branch": branch}
        if git(root, "status", "--porcelain", "--untracked-files=no", check=False):
            return {"state": "dirty", "branch": branch, "sha": sha}  # never overwrite the folder's own changes
        head = git(root, "rev-parse", "HEAD")
        # The commit the WIP was taken on, as far as the branch still has it (a later WIP has the previous one and
        # the new capture as parents; both lead back to the folder's HEAD at that turn).
        base = git(root, "merge-base", sha, head, check=False)
        if not _SHA.match(base):
            return {"state": "stale", "branch": branch, "sha": sha}
        moved = _names(root, base, head) if base != head else set()
        paths = sorted(_names(root, base, sha) - moved)
        if not paths:
            return {"state": "unchanged", "branch": branch, "sha": sha}
        with tempfile.NamedTemporaryFile("w", prefix="octryx-wip-paths-", encoding="utf-8") as listing:
            listing.write("\0".join(paths))
            listing.flush()
            git(root, "restore", f"--source={sha}", "--worktree", f"--pathspec-from-file={listing.name}",
                "--pathspec-file-nul", extra_env={"GIT_LITERAL_PATHSPECS": "1"})
        return {"state": "restored", "branch": branch, "sha": sha, "files": len(paths),
                **({"kept_branch": sorted(_names(root, base, sha) & moved)} if moved else {})}
    except WorkStateError as error:
        return {"state": "failed", "branch": branch, "reason": str(error) or "git_failed"}


BACKUP = ("octryx-reset-backup",)


def reset_tree(root: Path, run_id: str, sha: str) -> dict[str, Any]:
    try:
        if not _SHA.match(sha):
            return {"state": "failed", "sha": sha, "reason": "not_a_commit"}
        if not git(root, "cat-file", "-t", sha, check=False) == "commit":
            _fetch(root, "origin", run_id)
        if not git(root, "cat-file", "-t", sha, check=False) == "commit":
            return {"state": "failed", "sha": sha, "reason": "checkpoint_unavailable"}
        # Only what the later phases changed: the files that differ between the checkpoint and the run's latest WIP
        # (never the folder's other untracked files, e.g. a .env the WIP leaves out).
        latest = _fetch(root, "origin", run_id)
        if not latest:
            return {"state": "failed", "sha": sha, "reason": "no_wip"}
        changed = [name for name in git(root, "diff", "--name-only", "--no-renames", "-z", sha, latest,
                                        check=False).split("\0") if name]
        backup = root.joinpath(".git", *BACKUP, sha[:12])
        for name in dict.fromkeys(changed):
            current = root / name
            if current.is_file():
                target = backup / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, target)
            if _in_commit(root, sha, name):
                git(root, "restore", f"--source={sha}", "--worktree", "--", name,
                    extra_env={"GIT_LITERAL_PATHSPECS": "1"})
            elif current.is_file():
                current.unlink()  # its copy is in the backup
        return {"state": "done", "sha": sha, "files": len(dict.fromkeys(changed)),
                "backup": str(backup.relative_to(root))}
    except (WorkStateError, OSError) as error:
        return {"state": "failed", "sha": sha, "reason": str(error)[:120] or "git_failed"}


def _in_commit(root: Path, sha: str, name: str) -> bool:
    return bool(git(root, "ls-tree", "--name-only", sha, "--", name, check=False,
                    extra_env={"GIT_LITERAL_PATHSPECS": "1"}))


__all__ = ["PREFIX", "push_run_wip", "reset_tree", "restore_run_wip", "wip_branch"]
