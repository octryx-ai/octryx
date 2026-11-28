"""The work state of a handoff: a WIP branch of the session's git repository, made without touching the
user's working tree, index or current branch."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import os_junk
from .repository import credential_free_remote

GIT_TIMEOUT = 120.0
MAX_FILES_LISTED = 100
MAX_BUNDLE_BYTES = 50 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{40}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
# The gateway's path rules (``.env``, ``.aws/``) plus the key and credential files a handoff must never carry.
SECRET_NAME_PATTERNS = (
    ".env", ".env.*", "*.env", ".envrc",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "*.ppk",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd",
    "credentials", "credentials.*", "*.tfvars", "secrets.*",
    # judge-s4c probes: further secret-bearing files.
    "kubeconfig", "*.kubeconfig", ".pgpass", "*service-account*.json", "*.gpg", "*.asc", "*.tfstate", "*.tfstate.*",
)
SECRET_DIRECTORIES = (".aws", ".ssh", ".gnupg", ".docker")


class WorkStateError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkState:
    root: Path
    remote_url: str
    remote_name: str
    push_urls: list[str]
    base_commit: str
    wip_commit: str
    changed_files: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    last_commits: list[str] = field(default_factory=list)


def is_secret_path(path: str) -> bool:
    parts = [part.lower() for part in path.replace("\\", "/").split("/") if part]
    if any(part in SECRET_DIRECTORIES for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_NAME_PATTERNS)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    env.update(extra or {})
    return env


def git(root: Path, *args: str, extra_env: dict[str, str] | None = None, check: bool = True) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=GIT_TIMEOUT,
                                   env=_env(extra_env), check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise WorkStateError("git_unavailable") from error
    if check and completed.returncode != 0:
        raise WorkStateError("git_failed")
    return completed.stdout.decode("utf-8", errors="replace").strip()


def repository_root(cwd: Path | str) -> Path | None:
    try:
        top = git(Path(cwd), "rev-parse", "--show-toplevel")
    except WorkStateError:
        return None
    return Path(top) if top else None


def _remote(root: Path) -> tuple[str, str, list[str]]:
    names = sorted(name for name in git(root, "remote", check=False).splitlines() if name.strip())
    if not names:
        return "", "", []
    name = "origin" if "origin" in names else names[0]
    pushes = git(root, "remote", "get-url", "--push", "--all", name, check=False).splitlines()
    return (name, credential_free_remote(git(root, "remote", "get-url", name, check=False)),
            [credential_free_remote(url) for url in pushes if url.strip()])


_IN_PROGRESS = (("MERGE_HEAD", "merge_in_progress"), ("rebase-merge", "rebase_in_progress"),
                ("rebase-apply", "rebase_in_progress"), ("CHERRY_PICK_HEAD", "cherry_pick_in_progress"),
                ("REVERT_HEAD", "revert_in_progress"))


def _refuse_in_progress(root: Path) -> None:
    for name, code in _IN_PROGRESS:
        if Path(git(root, "rev-parse", "--path-format=absolute", "--git-path", name)).exists():
            raise WorkStateError(code)


def safe_segment(value: str) -> str:
    segment = re.sub(r"\.{2,}", ".", _UNSAFE.sub("-", value)).strip("-.")[:60]
    while segment.lower().endswith(".lock"):
        segment = segment[:-5].rstrip("-.")
    return segment or "x"


def branch_name(key: str, user: str, now: datetime) -> str:
    return f"octryx-handoff/{safe_segment(key)}/{safe_segment(user)}-{now.strftime('%Y%m%d-%H%M')}"


def capture_work_state(root: Path, *, user_name: str, user_email: str, message: str) -> WorkState:
    head = git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False)
    if not _SHA.match(head):
        raise WorkStateError("head_missing")
    _refuse_in_progress(root)
    with tempfile.TemporaryDirectory(prefix="octryx-handoff-index-") as scratch:
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(root, "read-tree", "HEAD", extra_env=index)
        git(root, *os_junk.add_all(), extra_env=index)
        changed = [path for path in git(root, "diff", "--cached", "--name-only", "-z", "HEAD", extra_env=index)
                   .split("\0") if path]
        excluded = sorted(path for path in changed if is_secret_path(path))
        literal = {**index, "GIT_LITERAL_PATHSPECS": "1"}  # ``x[1].pem``, ``:x.env`` are names, not patterns
        for path in excluded:
            # Back to HEAD's version in the temporary index (a new file drops out of it).
            git(root, "reset", "-q", "HEAD", "--", path, extra_env=literal)
        tree = git(root, "write-tree", extra_env=index)
    _require_excluded(root, tree, head, excluded)
    wip = head
    if tree != git(root, "rev-parse", "HEAD^{tree}"):
        author = {"GIT_AUTHOR_NAME": user_name, "GIT_AUTHOR_EMAIL": user_email,
                  "GIT_COMMITTER_NAME": user_name, "GIT_COMMITTER_EMAIL": user_email}
        wip = git(root, "commit-tree", "--no-gpg-sign", tree, "-p", head, "-m", message, extra_env=author)
    remote_name, remote_url, push_urls = _remote(root)
    commits = git(root, "log", "--format=%h %s", "-5", wip, check=False).splitlines()
    kept = [path for path in changed if path not in excluded]
    return WorkState(root=root, remote_url=remote_url, remote_name=remote_name, push_urls=push_urls,
                     base_commit=head, wip_commit=wip,
                     changed_files=kept[:MAX_FILES_LISTED], excluded_files=excluded[:MAX_FILES_LISTED],
                     last_commits=commits[:5])


def _require_excluded(root: Path, tree: str, head: str, excluded: list[str]) -> None:
    if not excluded:
        return
    literal = {"GIT_LITERAL_PATHSPECS": "1"}
    differing = set(git(root, "diff", "--name-only", "-z", head, tree, "--", *excluded, extra_env=literal)
                    .split("\0")) - {""}
    if differing:
        raise WorkStateError("secret_path_not_excluded")


def create_branch(root: Path, branch: str, commit: str) -> None:
    git(root, "update-ref", f"refs/heads/{branch}", commit, "0" * 40)


def free_branch_name(root: Path, branch: str) -> str:
    candidate, number = branch, 1
    while git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}", check=False):
        number += 1
        candidate = f"{branch}-{number}"
    return candidate


def _normalized(url: str) -> str:
    value = credential_free_remote(url).strip().rstrip("/")
    return (value[:-4] if value.endswith(".git") else value).lower()


# Every URL a push really goes to (``pushurl``, ``pushInsteadOf``) must be registered.
def may_push(policy_push: str, remote_url: str, registered: list[str], push_urls: list[str] | None = None) -> bool:
    if policy_push != "branch" or not remote_url or not push_urls:
        return False  # the push targets are unknown: never push (fail closed)
    allowed = {_normalized(url) for url in registered if url}
    targets = [remote_url, *push_urls]
    return all(_normalized(url) in allowed for url in targets)


PUSH_OPTIONS = ("-c", "push.followTags=false")
PUSH_FLAGS = ("--no-verify", "--no-follow-tags", "--recurse-submodules=no")


def push_branch(state: WorkState, branch: str, registered: list[str] | None = None) -> bool:
    if not state.remote_name or not state.push_urls:
        return False
    if registered is not None:
        if not may_push("branch", state.remote_url, registered, state.push_urls):
            return False
    elif any(_normalized(url) != _normalized(state.remote_url) for url in state.push_urls):
        return False
    try:
        git(state.root, *PUSH_OPTIONS, "push", *PUSH_FLAGS, state.remote_name,
            f"refs/heads/{branch}:refs/heads/{branch}")
    except WorkStateError:
        return False
    return True


def create_bundle(state: WorkState, branch: str, target: Path) -> bytes:
    if git(state.root, "rev-list", "-n", "1", f"refs/heads/{branch}", "--not", "--remotes", check=False):
        git(state.root, "bundle", "create", "-q", str(target), f"refs/heads/{branch}", "--not", "--remotes",
            check=False)
    if not target.exists():
        git(state.root, "bundle", "create", "-q", str(target), f"refs/heads/{branch}")
    data = target.read_bytes()
    if len(data) > MAX_BUNDLE_BYTES:
        raise WorkStateError("bundle_too_large")
    return data


__all__ = [
    "MAX_BUNDLE_BYTES",
    "WorkState",
    "WorkStateError",
    "branch_name",
    "capture_work_state",
    "create_branch",
    "create_bundle",
    "free_branch_name",
    "is_secret_path",
    "may_push",
    "push_branch",
    "repository_root",
]
