"""The git repository of the launch folder, read through the local ``git`` binary."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

GIT_TIMEOUT = 10.0
LS_TREE_TIMEOUT = 30.0
CAT_FILE_TIMEOUT = 60.0
MAX_TREE_FILES = 10000
MAX_OUTPUT_LINE_CHARS = 2000

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REGULAR_MODES = {b"100644", b"100755"}


@dataclass(frozen=True)
class DetectionRefusal:
    code: str


@dataclass(frozen=True)
class RepositoryInfo:
    root: Path
    remote_url: str
    head_commit: str
    head_dirty: bool
    head_pushed: bool
    branch: str | None


@dataclass(frozen=True)
class TreeFile:
    path: str
    blob_sha: str
    size: int


@dataclass(frozen=True)
class TreeListing:
    files: list[TreeFile] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class _GitRun:
    ok: bool
    stdout: bytes = b""
    unavailable: bool = False


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"})
    return env


def _git(cwd: Path, *args: str, timeout: float = GIT_TIMEOUT, stdin: bytes | None = None) -> _GitRun:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd), input=stdin, capture_output=True,
            timeout=timeout, env=_git_env(), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Missing binary, unreadable cwd or timeout: git cannot answer.
        return _GitRun(ok=False, unavailable=True)
    return _GitRun(ok=completed.returncode == 0, stdout=completed.stdout)


def _line(run: _GitRun) -> str:
    return run.stdout.decode("utf-8", errors="replace").strip()[:MAX_OUTPUT_LINE_CHARS]


# The scp form's ``git@`` user is no credential; ``ssh://`` URLs keep the user and lose the password.
def credential_free_remote(raw: str) -> str:
    value = raw.strip()
    if "://" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    host = parts.netloc.rpartition("@")[2]
    if scheme in ("http", "https"):
        return urlunsplit((scheme, host, parts.path, "", ""))
    if scheme in ("ssh", "git+ssh") and "@" in parts.netloc:
        user = parts.netloc.rpartition("@")[0].partition(":")[0]
        return urlunsplit((scheme, f"{user}@{host}" if user else host, parts.path, "", ""))
    return urlunsplit((scheme, host, parts.path, "", ""))


def _remote_url(root: Path) -> str:
    listed = _git(root, "remote")
    if not listed.ok:
        return ""
    names = sorted(name for name in _line(listed).splitlines() if name.strip())
    if not names:
        return ""
    name = "origin" if "origin" in names else names[0]
    url = _git(root, "remote", "get-url", name)
    return credential_free_remote(_line(url)) if url.ok else ""


def detect_repository(cwd: Path | str) -> RepositoryInfo | DetectionRefusal:
    toplevel = _git(Path(cwd), "rev-parse", "--show-toplevel")
    if toplevel.unavailable:
        return DetectionRefusal("git_unavailable")
    if not toplevel.ok or not _line(toplevel):
        return DetectionRefusal("not_a_git_repository")
    root = Path(_line(toplevel))
    head = _git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    if head.unavailable:
        return DetectionRefusal("git_unavailable")
    head_commit = _line(head)
    if not head.ok or not _SHA.match(head_commit):
        return DetectionRefusal("head_missing")
    remote_url = _remote_url(root)
    if not remote_url:
        return DetectionRefusal("remote_missing")
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    pushed = _git(root, "branch", "-r", "--contains", "HEAD")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    branch_name = _line(branch) if branch.ok else ""
    return RepositoryInfo(
        root=root,
        remote_url=remote_url,
        head_commit=head_commit,
        # A status that cannot be read counts as dirty: HEAD may not be what you see.
        head_dirty=bool(status.stdout.strip()) if status.ok else True,
        head_pushed=pushed.ok and bool(pushed.stdout.strip()),
        branch=branch_name if branch_name and branch_name != "HEAD" else None,
    )


def parse_ls_tree(output: bytes, *, limit: int = MAX_TREE_FILES) -> TreeListing:
    files: list[TreeFile] = []
    for entry in output.split(b"\0"):
        meta, tab, raw_path = entry.partition(b"\t")
        fields = meta.split()
        if not tab or len(fields) != 4:
            continue
        mode, kind, sha, size = fields
        if kind != b"blob" or mode not in _REGULAR_MODES or not size.isdigit():
            continue  # symlinks (120000), submodules (160000) and anything unexpected
        try:
            path = raw_path.decode("utf-8")
            blob_sha = sha.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not path or not _SHA.match(blob_sha):
            continue
        if len(files) >= limit:
            return TreeListing(files, truncated=True)
        files.append(TreeFile(path, blob_sha, int(size)))
    return TreeListing(files, truncated=False)


def list_head_files(root: Path | str) -> TreeListing | DetectionRefusal:
    run = _git(Path(root), "ls-tree", "-r", "-l", "-z", "HEAD", timeout=LS_TREE_TIMEOUT)
    if not run.ok:
        return DetectionRefusal("tree_unavailable")
    return parse_ls_tree(run.stdout)


def parse_cat_file_batch(output: bytes) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    position = 0
    while position < len(output):
        newline = output.find(b"\n", position)
        if newline < 0:
            break
        header = output[position:newline].split()
        position = newline + 1
        if len(header) != 3 or not header[2].isdigit():
            continue  # "<sha> missing" and other one-line answers carry no content
        size = int(header[2])
        content = output[position:position + size]
        position += size + 1
        if len(content) != size:
            break
        if header[1] == b"blob":
            blobs[header[0].decode("ascii", errors="replace")] = content
    return blobs


def read_blobs(root: Path | str, shas: list[str]) -> dict[str, bytes]:
    wanted = [sha for sha in dict.fromkeys(shas) if _SHA.match(sha)]
    if not wanted:
        return {}
    request = "".join(f"{sha}\n" for sha in wanted).encode("ascii")
    run = _git(Path(root), "cat-file", "--batch", timeout=CAT_FILE_TIMEOUT, stdin=request)
    if not run.ok:
        return {}
    blobs = parse_cat_file_batch(run.stdout)
    return {sha: blobs[sha] for sha in wanted if sha in blobs}
