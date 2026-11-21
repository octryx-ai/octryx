"""The folder's git for the run preparation (``workspace_prep``): the repository check, catching up with the
platform's commit and what an earlier run left in the folder.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .contract_change import SAFE_GIT
from .work_git_commit import IDENTITY, ITEMS_DIR

GIT_TIMEOUT = 60
_BRANCH = re.compile(r"^(?!-)(?!/)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}$")
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_SCP = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.-]+):(?P<path>(?!/)[^\s]+)$")
_HOST_ALIASES = {"api.github.com": "github.com", "api.bitbucket.org": "bitbucket.org"}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run([*SAFE_GIT, *args], cwd=root, capture_output=True, text=True, errors="replace",
                              timeout=GIT_TIMEOUT, check=False, stdin=subprocess.DEVNULL,
                              env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                                   "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None


def _ok(done: subprocess.CompletedProcess | None) -> bool:
    return done is not None and done.returncode == 0


def _out(done: subprocess.CompletedProcess | None) -> str:
    return (done.stdout or "").strip() if done is not None else ""


def origin_url(root: Path) -> str:
    """The folder's ``origin`` remote without any user info (a token in a URL never leaves the device)."""
    url = _out(_git(root, "remote", "get-url", "origin"))
    if "://" in url:
        parts = urlsplit(url)
        host = parts.hostname or ""
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return url.split("@", 1)[-1] if _SCP.match(url) else ""


def _host_and_path(url: str) -> tuple[str, str]:
    if "://" in url:
        parts = urlsplit(url)
        host, path = (parts.hostname or "").lower(), parts.path
    elif match := _SCP.match(url):
        host, path = match.group("host").lower(), match.group("path")
    else:
        return "", ""
    segments = [item for item in path.strip("/").removesuffix(".git").lower().split("/") if item]
    if "scm" in segments[:-2]:
        segments = segments[segments.index("scm") + 1:]  # Bitbucket Server clones from <context>/scm/<key>/<slug>
    return _HOST_ALIASES.get(host, host), "/".join(segments)


def repository_refusal(root: Path, expected: dict[str, Any] | None) -> str:
    """Why the folder is not the run's repository ("" when it is, or the run names no repository to compare)."""
    if not isinstance(expected, dict) or not expected.get("hosts") or not expected.get("path"):
        return ""
    url = origin_url(root)
    host, path = _host_and_path(url)
    hosts = {str(item).lower() for item in expected.get("hosts") or []}
    if host in hosts and path == str(expected.get("path") or "").lower():
        return ""
    return (f"its origin is {url or 'not set'}, the run works on {expected.get('path')} "
            f"({', '.join(sorted(hosts))}); nothing was changed in the folder")


def _has_commit(root: Path, head: str) -> bool:
    return bool(_SHA.match(head or "")) and _ok(_git(root, "cat-file", "-e", f"{head}^{{commit}}"))


def _catch_up(root: Path, head: str | None) -> str:
    """Bring a local branch that is behind the platform's commit up to it; why not ("" when it is fine).

    : a second run on the same Work item found its branch from the first run still at the old base;
    origin could not be fetched from the device, so the run built on a master without the new system tests."""
    if not head or not _has_commit(root, head):
        return ""
    current = _out(_git(root, "rev-parse", "HEAD"))
    if current == head or _ok(_git(root, "merge-base", "--is-ancestor", head, "HEAD")):
        return ""  # at the commit, or ahead of it with this run's own work
    if _ok(_git(root, "merge-base", "--is-ancestor", "HEAD", head)):
        done = _git(root, "merge", "--ff-only", head)
        return "" if _ok(done) else ((done.stderr if done is not None else "") or "fast-forward failed").strip()[:300]
    return (f"the local branch is at {current[:12]}, which is not part of the run's branch at {head[:12]} "
            "(left over from an earlier run?): rename or remove the local branch, then retry")


# A branch the platform named for an earlier run ("feature/-...", "docs/-..."): its leftovers in the
# folder are that run's own edits, which the platform pushed from its server copy; left in place they would keep the
# next story of an epic chain from starting.
_RUN_BRANCH = re.compile(r"^(feature|bugfix|docs|chore|fix|hotfix)/[A-Z][A-Z0-9]*-\d+(-|$)")


def _stash_run_leftovers(root: Path, branch: str) -> str:
    """Set the leftovers of an earlier run's branch aside in a named stash (nothing is lost; ``git stash list``
    shows it); the stash message, or ``""`` when stashing failed."""
    message = f"{LEFTOVERS} {branch} {time.strftime('%Y-%m-%dT%H:%M:%S')}"
    done = _git(root, "stash", "push", "--include-untracked", "-m", message)
    return message if _ok(done) else ""


LEFTOVERS = "octryx-leftovers"
PLATFORM_AUTHOR = IDENTITY[1].split("=", 1)[1]  # the platform's own commits (``backend safe_git.IDENTITY``)


def _names(done: subprocess.CompletedProcess | None) -> set[str]:
    return {name for name in (done.stdout or "").split("\0") if name} if _ok(done) else set()


def _in_head(root: Path, stash: str) -> bool:
    """Whether every file a leftovers stash holds is at HEAD with the same content (tracked and untracked parts):
    the earlier run's edits reached this branch through the platform's push."""
    changed = _names(_git(root, "diff", "--name-only", "-z", "--no-renames", f"{stash}^1", stash))
    if changed & _names(_git(root, "diff", "--name-only", "-z", "--no-renames", stash, "HEAD")):
        return False
    if not _ok(_git(root, "rev-parse", "--verify", "--quiet", f"{stash}^3")):
        return True
    untracked = _names(_git(root, "ls-tree", "-r", "-z", "--name-only", f"{stash}^3"))
    return not untracked & _names(_git(root, "diff", "--name-only", "-z", "--no-renames", f"{stash}^3", "HEAD"))


def drop_pushed_leftovers(root: Path) -> list[str]:
    """Drop the leftovers stashes whose files are all on the branch now (the stashed branch was pushed and this
    story builds on it); the others stay, so leftovers stashes do not pile up story after story. The dropped stash
    messages."""
    listing = _git(root, "stash", "list", "--format=%H %gs")
    entries = [line.split(" ", 1) for line in _out(listing).splitlines() if " " in line]
    dropped = []
    for index in reversed(range(len(entries))):  # from the oldest: a drop never renumbers the ones still to check
        sha, message = entries[index]
        if LEFTOVERS in message and _in_head(root, sha) and _ok(_git(root, "stash", "drop", f"stash@{{{index}}}")):
            dropped.append(message.split(": ", 1)[-1])
    return dropped


def _item_worktrees(root: Path) -> list[Path]:
    items = Path(os.path.realpath(root / ITEMS_DIR))
    listing = _out(_git(root, "worktree", "list", "--porcelain"))
    paths = [Path(os.path.realpath(line[len("worktree "):])) for line in listing.splitlines()
             if line.startswith("worktree ")]
    return [path for path in paths if path.parent == items]


def _platform_only(root: Path, head: str, branch: str) -> list[str]:
    """The commits of ``branch`` beyond ``head`` when every one on its first-parent line is the platform's own (the
    work-plan and merge commits of an earlier run) and none of them is on ``origin`` already; ``[]`` otherwise
    (none, a person's commit among them, or pushed work the device knows of)."""
    done = _git(root, "log", "--first-parent", "--format=%H %an", f"{head}..refs/heads/{branch}")
    rows = [line.split(" ", 1) for line in _out(done).splitlines() if " " in line] if _ok(done) else []
    if not rows or any(author != PLATFORM_AUTHOR for _, author in rows):
        return []
    remote = f"refs/remotes/origin/{branch}"
    if _ok(_git(root, "rev-parse", "--verify", "--quiet", remote)):
        local_only = _out(_git(root, "rev-list", "--count", f"{head}..refs/heads/{branch}", f"^{remote}"))
        if local_only != _out(_git(root, "rev-list", "--count", f"{head}..refs/heads/{branch}")):
            return []
    return [sha for sha, _ in rows]


def discard_earlier_run(root: Path, branch: str, head: str | None) -> dict[str, Any]:
    """Clean what an earlier run of this branch left on the device, before a new run's first git work: its item
    worktrees, its ``<branch>--<key>`` branches and the platform's local commits on the run branch (reset to the
    commit the platform knows the branch at: pushed, or the base). Nothing is lost: the old tip stays under
    ``refs/octryx/leftovers/``, uncommitted files in a named stash.

    A rerun of an aborted story must not inherit its ``.octryx-items`` worktrees, item branches and work-plan commits
    into the change and the PR. The platform says when the run has no git work of its own on the device yet
    (``preparation.run_commits_on_device: false``); only then is anything here an earlier run's."""
    cleaned: dict[str, Any] = {}
    worktrees = _item_worktrees(root)
    for path in worktrees:
        _git(root, "worktree", "remove", "--force", str(path))
    _git(root, "worktree", "prune")
    if worktrees:
        cleaned["worktrees"] = sorted(path.name for path in worktrees)
    refs = _out(_git(root, "for-each-ref", "--format=%(refname:strip=2)", f"refs/heads/{branch}--*")).splitlines()
    if refs and _ok(_git(root, "branch", "-D", *refs)):
        cleaned["branches"] = refs
    if not head or not _has_commit(root, head) or not _platform_only(root, head, branch):
        return cleaned
    tip = _out(_git(root, "rev-parse", f"refs/heads/{branch}"))
    _git(root, "update-ref", f"refs/octryx/leftovers/{branch}/{time.strftime('%Y%m%dT%H%M%S')}", tip)
    if _out(_git(root, "rev-parse", "--abbrev-ref", "HEAD")) == branch:
        if _out(_git(root, "status", "--porcelain", "--untracked-files=all")):
            _stash_run_leftovers(root, branch)
        reset = _git(root, "reset", "-q", "--hard", head)
    else:
        reset = _git(root, "branch", "-f", branch, head)
    if _ok(reset):
        cleaned["reset"] = {"from": tip, "to": head}
    return cleaned


#: Asks the platform for the run's branch as a git bundle; gets the commits the device has, answers the platform's
