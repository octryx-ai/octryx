"""The run's branch as a git bundle for a device that cannot fetch from origin (``POST sessions/branch-bundle``).

A device's launcher may have no git credentials for
a repository host it cannot reach on its own ("could not read Username for '<host>'"). The
platform pushes each story's commit from its own working copy and the next story starts from it, so at every story
transition the device would lack the commit and the run would pause until a person fetched by hand.

The platform's working copy of the run (``run.context.local_path``) has the commits. The launcher asks over its
authenticated control-plane session, only for the run its session is bound to, and names the commits it has
(``have``); the bundle then carries only what is missing (those commits are its prerequisites). When the
prerequisites do not work out (nothing new, an unknown commit), the bundle is the branch's whole history.

The bundled ref is ``refs/heads/<run.branch>`` when the working copy has the branch; else (the run's branch is not
in the server copy yet) the commit the platform knows the branch at (``preparation.requirement`` ``head``) under a
short-lived ref, so the device can start the branch there.
"""

from __future__ import annotations

import base64
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ....models import WorkflowRun
from ..safe_git import git

REASON_NO_WORKING_COPY = "run_has_no_working_copy"
REASON_NO_BRANCH = "branch_not_in_working_copy"
REASON_BUNDLE_FAILED = "bundle_failed"
_SHA = re.compile(r"^[0-9a-f]{40,64}$")


def _known_head(run: WorkflowRun) -> str:
    context = dict(run.context or {})
    return str(dict(context.get("branch_adoption") or {}).get("head") or context.get("base_sha") or "")


async def _commits_here(root: Path, candidates: list[str]) -> list[str]:
    """The device's commits that this working copy has too (only those can be prerequisites)."""
    wanted = list(dict.fromkeys(str(item) for item in candidates if _SHA.match(str(item or ""))))
    if not wanted:
        return []
    code, out, _err = await git(root, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                                stdin=("\n".join(wanted) + "\n").encode())
    if code != 0:
        return []
    return [line.split()[0] for line in out.splitlines() if line.endswith(" commit")]


async def _create(root: Path, target: Path, ref: str, have: list[str]) -> str:
    """'' when the bundle was written; else git's reason."""
    code, _out, err = await git(root, "bundle", "create", "-q", str(target), ref, *[f"^{sha}" for sha in have])
    return "" if code == 0 else (err.strip() or "git bundle failed")


async def branch_bundle(run: WorkflowRun, have: list[Any]) -> dict[str, Any]:
    """``{"state": "ready", "branch", "ref", "head", "bundle" (base64), "prerequisites"}`` or a refusal
    ``{"state": "unavailable", "reason", "detail"}``."""
    local_path = str(dict(run.context or {}).get("local_path") or "")
    root = Path(local_path) if local_path else None
    if root is None or not (root / ".git").exists():
        return {"state": "unavailable", "reason": REASON_NO_WORKING_COPY,
                "detail": "the run has no working copy on the platform"}
    branch = str(run.branch or "")
    ref = f"refs/heads/{branch}"
    code, out, _err = await git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    temporary = ""
    if code != 0 or not branch:
        known = _known_head(run)
        if not (await _commits_here(root, [known])):
            return {"state": "unavailable", "reason": REASON_NO_BRANCH,
                    "detail": f"the platform's working copy has neither the branch '{branch}' nor its commit"}
        temporary = ref = f"refs/octryx-bundle/{uuid.uuid4().hex}"
        await git(root, "update-ref", ref, known)
        out = known
    head = out.strip()
    try:
        with tempfile.TemporaryDirectory(prefix="octryx-bundle-") as scratch:
            target = Path(scratch) / "branch.bundle"
            prerequisites = [sha for sha in await _commits_here(root, list(have or [])) if sha != head]
            failed = await _create(root, target, ref, prerequisites) if prerequisites else "full"
            if failed:
                prerequisites = []
                failed = await _create(root, target, ref, [])
            if failed:
                return {"state": "unavailable", "reason": REASON_BUNDLE_FAILED, "detail": failed[:500]}
            data = target.read_bytes()
    finally:
        if temporary:
            await git(root, "update-ref", "-d", temporary)
    return {"state": "ready", "branch": branch, "ref": ref, "head": head, "prerequisites": prerequisites,
            "bundle": base64.b64encode(data).decode("ascii")}


__all__ = ["REASON_BUNDLE_FAILED", "REASON_NO_BRANCH", "REASON_NO_WORKING_COPY", "branch_bundle"]
