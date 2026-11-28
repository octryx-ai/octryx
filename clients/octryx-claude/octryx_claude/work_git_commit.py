"""The git primitives of the ``parallel_work`` git work: identity, runtime excludes and the platform's commits."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .contract_change import SAFE_GIT

ITEMS_DIR = ".octryx-items"
EXCLUDE = f"/{ITEMS_DIR}/"
# Never in an item's merge, the change or the push, whatever .gitignore says: test reports, screenshots, setup build
# output and engine installs bloated the review diff and conflicted in merges. Untracked files only, at any depth.
RUNTIME_EXCLUDES = (EXCLUDE, "/test-reports/", "/.pytest_cache/", "/.venv/", "*.db", "*.egg-info/", "__pycache__/",
                    "/build/", "/dist/", "node_modules/", ".npm-cache/", ".playwright-browsers/", "test-results/",
                    "playwright-report/", ".octryx-eslint.config.mjs")  # the platform's own lint config (style_tools)
# The platform's own commits (``backend safe_git.IDENTITY``): a later run tells them from a person's.
IDENTITY = ("-c", "user.name=Octryx workflow run", "-c", "user.email=workflow-run@octryx.invalid",
            "-c", "commit.gpgsign=false")
GIT_TIMEOUT = 120


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:  # ``errors="replace"``: a file name or message that is not UTF-8 never ends the git work
        return subprocess.run([*SAFE_GIT, *IDENTITY, *args], cwd=root, capture_output=True, text=True, check=False,
                              errors="replace", timeout=GIT_TIMEOUT, stdin=subprocess.DEVNULL,
                              env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                                   "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def _error(done: subprocess.CompletedProcess) -> str:
    return ((done.stderr or "") + (done.stdout or "")).strip()[-500:] or f"git exited {done.returncode}"


def exclude_runtime_files(root: Path) -> None:
    target = _git(root, "rev-parse", "--git-path", "info/exclude")
    if target.returncode != 0:
        return
    exclude = Path(root) / target.stdout.strip()
    lines = exclude.read_text().splitlines() if exclude.is_file() else []
    missing = [pattern for pattern in RUNTIME_EXCLUDES if pattern not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, *missing]) + "\n")


def commit_all(folder: Path, message: str) -> str:
    added = _git(folder, "add", "-A")
    if added.returncode != 0:
        return _error(added)
    merging = _git(folder, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
    if not merging and _git(folder, "diff", "--cached", "--quiet").returncode == 0:
        return ""  # a merge the agent resolved to its own side still needs its commit (both parents)
    done = _git(folder, "commit", "-q", "--no-verify", "-m", message)
    return "" if done.returncode == 0 else _error(done)


def _merged_item_files(root: Path, base: str) -> set[str]:
    span = [f"{base}..HEAD"] if base and _git(root, "cat-file", "-e", f"{base}^{{commit}}").returncode == 0 \
        else ["HEAD"]
    merges = _git(root, "log", "--first-parent", "--merges", "--format=%H%x00%an%x00%s", *span)
    owned: set[str] = set()
    for line in merges.stdout.splitlines() if merges.returncode == 0 else []:
        sha, author, subject = (line.split("\0") + ["", ""])[:3]
        if author == IDENTITY[1].split("=", 1)[1] and subject.startswith("Merge item "):
            listed = _git(root, "diff", "--name-only", "-z", "--no-renames", f"{sha}^1", sha)
            owned.update(name for name in listed.stdout.split("\0") if name)
    return owned


def commit_main(root: Path, message: str, base: str = "") -> tuple[str, list[str]]:
    # A folder that lost merged files (a stale WIP restored over it) would otherwise stage their deletion.
    added = _git(root, "add", "-A")
    if added.returncode != 0:
        return _error(added), []
    staged = _git(root, "diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=D", "HEAD")
    deleted = {name for name in staged.stdout.split("\0") if name} if staged.returncode == 0 else set()
    kept = sorted(deleted & _merged_item_files(root, base)) if deleted else []
    if kept:
        with tempfile.NamedTemporaryFile("w", prefix="octryx-kept-", encoding="utf-8") as listing:
            listing.write("\0".join(kept))
            listing.flush()
            done = _git(root, "--literal-pathspecs", "restore", "--source=HEAD", "--staged", "--worktree",
                        f"--pathspec-from-file={listing.name}", "--pathspec-file-nul")
        if done.returncode != 0:
            return f"putting back the merged items' files failed: {_error(done)}", kept
    return commit_all(root, message), kept


def _message(title: str, trailer: str) -> str:
    return title + (f"\n\n{trailer.strip()}" if trailer.strip() else "")


def _exclude(root: Path, patterns: list[str]) -> None:
    target = _git(root, "rev-parse", "--git-path", "info/exclude")
    if target.returncode != 0:
        return
    exclude = Path(root) / target.stdout.strip()
    lines = exclude.read_text().splitlines() if exclude.is_file() else []
    missing = [pattern for pattern in patterns if pattern not in lines]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join([*lines, *missing]) + "\n")
