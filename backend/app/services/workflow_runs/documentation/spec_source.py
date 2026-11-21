"""The specification a run pushed: ``SPEC.md`` at the pushed head, read from the run's working copy."""

from __future__ import annotations

from pathlib import Path

from ....models import WorkflowRun

MAX_SPEC_BYTES = 400_000
SPEC_DEPTH = 4


def _nearness(spec: str, touched: set[str]) -> int:
    """How many leading folders the spec shares with the files the pushed commit changed (the deepest match).

    With ``web/claude/SPEC.md`` and ``web/codex/SPEC.md`` in one repository, a story's commit (which changes no
    SPEC.md) would otherwise pick the first by name, so the Codex epic would publish the Claude spec."""
    folder = Path(spec).parent.parts
    best = 0
    for path in touched:
        parts = Path(path).parent.parts
        shared = 0
        for mine, theirs in zip(folder, parts):
            if mine != theirs:
                break
            shared += 1
        best = max(best, shared)
    return best


async def pushed_spec(run: WorkflowRun) -> tuple[str, str]:
    """``(path, text)`` of the specification the run pushed (``SPEC.md`` up to :data:`SPEC_DEPTH` folders deep at the
    pushed head, the one the pushed commit changed first), read from the run's working copy; ``("", "")`` when there
    is none. A repository may keep it e.g. at ``app/web/<engine>/SPEC.md`` (three folders)."""
    from ..phase_workspace import run_working_copy
    from ..safe_git import git

    root = run_working_copy(run)
    head = str(dict(run.context or {}).get("head_sha") or "")
    if root is None or not head:
        return "", ""
    code, listed, _err = await git(root, "ls-tree", "-r", "--name-only", head)
    if code != 0:
        return "", ""
    specs = [path for path in listed.splitlines() if Path(path).name == "SPEC.md" and path.count("/") <= SPEC_DEPTH]
    if not specs:
        return "", ""
    _code, changed, _err = await git(root, "show", "--name-only", "--format=", head)
    touched = set(changed.splitlines())
    path = sorted(specs, key=lambda item: (item not in touched, -_nearness(item, touched), item.count("/"), item))[0]
    code, text, _err = await git(root, "show", f"{head}:{path}")
    return (path, text[:MAX_SPEC_BYTES]) if code == 0 else ("", "")
