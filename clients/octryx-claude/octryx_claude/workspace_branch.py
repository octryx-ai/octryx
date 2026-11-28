"""Put the launch folder on the run's branch (``workspace_prep`` step 1): fetch from origin, or the platform's
bundle when this device cannot (a server runner: through ``git_gateway``), and set up a new folder."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .git_gateway import GatewaySource
from .workspace_git import (
    _BRANCH,
    _HOST_ALIASES,
    _RUN_BRANCH,
    _SHA,
    _catch_up,
    _git,
    _has_commit,
    _host_and_path,
    _ok,
    _out,
    _stash_run_leftovers,
    origin_url,
)

#: Asks the platform for the run's branch as a git bundle; gets the commits the device has, answers the platform's
#: body (``state``, ``ref``, ``bundle`` base64) or ``None``.
BundleSource = Callable[[list[str]], "dict[str, Any] | None"]


GATEWAY_FETCH_TIMEOUT = 600  # a whole branch history can take a while on a slow link


def _fetch_run_branch(root: Path, branch: str, gateway: GatewaySource | None) -> subprocess.CompletedProcess | None:
    refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
    if gateway is None:
        return _git(root, "fetch", "origin", refspec)
    source = gateway()
    if source is None:
        return None
    url, env = source
    return _git(root, "fetch", "--no-tags", url, refspec, env=env, timeout=GATEWAY_FETCH_TIMEOUT)


def _commits_on_device(root: Path) -> list[str]:
    # the platform bundles only what the device lacks
    tips = _out(_git(root, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/remotes")).splitlines()
    head = _git(root, "rev-parse", "HEAD")
    return [sha for sha in dict.fromkeys([_out(head) if _ok(head) else "", *tips]) if _SHA.match(sha)]


def _fetch_bundle(root: Path, branch: str, source: BundleSource) -> subprocess.CompletedProcess | None:
    # Without git credentials for the host, each story would start from a stale commit the platform pushed. A
    # bundle of a branch the platform lacks carries only its known commit under another ref name.
    answer = source(_commits_on_device(root))
    if not isinstance(answer, dict) or answer.get("state") != "ready" or not answer.get("bundle"):
        return None
    ref = str(answer.get("ref") or "")
    if not ref.startswith("refs/"):
        return None
    with tempfile.TemporaryDirectory(prefix="octryx-bundle-") as scratch:
        bundle = Path(scratch) / "branch.bundle"
        try:
            bundle.write_bytes(base64.b64decode(str(answer["bundle"]), validate=True))
        except ValueError:
            return None
        target = f"+{ref}:refs/remotes/origin/{branch}" if ref == f"refs/heads/{branch}" else ref
        return _git(root, "fetch", "--no-tags", str(bundle), target)


def _unborn(root: Path) -> bool:
    return (root / ".git").exists() and not _ok(_git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"))


def remote_for(repository: dict[str, Any] | None) -> str:
    # an API host is never the clone host
    if not isinstance(repository, dict):
        return ""
    url = str(repository.get("remote_url") or "")
    if url and (_host_and_path(url)[0] or "").strip():
        return url
    hosts = [str(item).lower() for item in repository.get("hosts") or [] if str(item)]
    hosts = [item for item in hosts if item not in _HOST_ALIASES] or hosts
    path = str(repository.get("path") or "").strip("/")
    return f"https://{hosts[0]}/{path}.git" if hosts and path else ""


def bootstrap(root: Path, repository: dict[str, Any] | None) -> str:
    # No clone: a device without git credentials for the remote gets the branch from the platform's bundle.
    if _ok(_git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")):
        return ""  # a working copy with commits
    if not (root / ".git").exists() and _ok(_git(root, "rev-parse", "--git-dir")):
        return ""  # a folder inside another working copy is never initialised on its own
    url = remote_for(repository)
    if not url:
        return "the folder is not a git working copy and the run names no repository to set it up from"
    if not (root / ".git").exists() and not _ok(_git(root, "init", "-q")):
        return "git init failed in the folder"
    if origin_url(root):
        return ""
    done = _git(root, "remote", "add", "origin", url)
    return "" if _ok(done) else ((done.stderr if done is not None else "") or "setting origin failed").strip()[:300]


def _already_on(root: Path, branch: str, head: str | None, bundle_source: BundleSource | None,
                gateway: GatewaySource | None = None) -> dict[str, Any]:
    if head and bundle_source is not None and not _has_commit(root, head) and \
            not _ok(_fetch_run_branch(root, branch, gateway)):
        _fetch_bundle(root, branch, bundle_source)  # the platform's newer commit, then fast-forwarded below
    stale = _catch_up(root, head)
    if stale:
        return {"state": "unavailable", "name": branch, "current": branch, "detail": stale}
    return {"state": "already", "name": branch, "head": _out(_git(root, "rev-parse", "HEAD"))}


def _dirty_or_stashed(root: Path, name: str) -> tuple[list[str], str]:
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    dirty = [line[3:] for line in (status.stdout or "").splitlines() if line.strip()] if _ok(status) else []
    stashed = ""
    leftovers = dirty
    if not dirty and _RUN_BRANCH.match(name):  # new files of the earlier run block the checkout as well
        untracked = _git(root, "status", "--porcelain", "--untracked-files=all")
        leftovers = [line for line in (untracked.stdout or "").splitlines() if line.strip()] if _ok(untracked) else []
    if leftovers and _RUN_BRANCH.match(name):
        stashed = _stash_run_leftovers(root, name)
        if stashed:
            dirty = []
    return dirty, stashed


def prepare_branch(root: Path, branch: str, head: str | None = None, bundle_source: BundleSource | None = None,
                   gateway: GatewaySource | None = None) -> dict[str, Any]:
    if not _BRANCH.match(branch or ""):
        return {"state": "unavailable", "name": branch, "detail": "the run names no valid branch"}
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not _ok(current) and not _unborn(root):
        return {"state": "unavailable", "name": branch, "detail": "the folder is not a git working copy"}
    name = _out(current) if _ok(current) else ""  # a bootstrapped folder has no commit yet: nothing to keep
    if name == branch:
        return _already_on(root, branch, head, bundle_source, gateway)
    dirty, stashed = _dirty_or_stashed(root, name)
    if dirty:  # nothing is stashed, reset or overwritten: a person decides
        return {"state": "dirty", "name": branch, "current": name, "dirty_files": dirty[:20],
                "detail": f"the folder is on '{name}' with uncommitted changes to {len(dirty)} tracked file(s)"}
    fetched = _fetch_run_branch(root, branch, gateway)
    if not _ok(fetched) and bundle_source is not None and not (head and _has_commit(root, head)):
        bundled = _fetch_bundle(root, branch, bundle_source)
        if _ok(bundled) and _ok(_git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")):
            fetched = bundled  # the branch itself: continue as if fetched from origin
    if _ok(_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")):
        done = _git(root, "checkout", branch)
        if _ok(done) and _ok(fetched):
            _git(root, "merge", "--ff-only", f"origin/{branch}")  # behind → fast-forward; diverged → kept
    elif _ok(fetched):
        done = _git(root, "checkout", "-b", branch, "--track", f"origin/{branch}")
    elif head and _has_commit(root, head):
        done = _git(root, "checkout", "-b", branch, head)  # origin unreachable from here: the platform's commit
    else:
        error = (fetched.stderr or "").strip()[:300] if fetched is not None else "git unavailable"
        missing = f" and this folder does not have the branch's commit {head[:12]}" if head else ""
        if bundle_source is not None:
            missing += " (nor could the platform hand it over)"
        return {"state": "unavailable", "name": branch, "current": name,
                "detail": f"this device could not fetch the branch from origin ({error}){missing}: give this device "
                          "read access to origin (an SSH key or a git credential helper) or pull it, then retry"}
    if not _ok(done):
        return {"state": "unavailable", "name": branch, "current": name,
                "detail": ((done.stderr if done is not None else "") or "checkout failed").strip()[:300]}
    stale = _catch_up(root, head)
    if stale:
        return {"state": "unavailable", "name": branch, "current": name, "detail": stale}
    return {"state": "checked_out", "name": branch, "previous": name, "head": _out(_git(root, "rev-parse", "HEAD")),
            **({"stashed": stashed} if stashed else {})}
