"""Prepare a run's server working copy, re-creating one that is gone.

Why: a run could record its working copy under ``/tmp/octryx-session-workspaces/…``;
when the API container was recreated (``/tmp`` is not persistent) the copy was gone. No action recreated it: the
server prepare (``server_prepare.prepare_locally``) only reports "not a git working copy", and the only clone lives in
``scm.create_branch``, which (rightly) never runs twice. Every phase of the run stayed held ``needs_configuration``.

:func:`prepare_on_server` is the one service both server prepare paths call — the Prepare step and "Change where the
run executes" → Server (also from a held phase; who may is the run-action gate, ``access.require_run(write=True)``,
which also claims the run). A run whose recorded copy exists is prepared; a run that never recorded one too.
A **recorded copy that is gone** is re-created only when that provably rebuilds the run's state — a re-clone restores
what the remote has, nothing else:

1. **No local work can be lost.** Refused ``recovery_unverified`` (a person decides) when the run's record shows
   anything a lost copy may have held beyond the remote: a change/deliver phase entered, a phase turn that used a
   writing, shell or test tool (``context.evidence``), a test run, an independent review, slices. Such evidence is
   bound to the lost tree and is never carried over to a new one. B at Clarify (read-only tools only) has none.
2. **Same run, same binding, same identity.** The provider's governed ``prepare_<provider>_repository`` tool through
   ``dispatch_tool``: the run's repository and branch, the run's requester as identity, and every check of a platform
   action (capability, approval, connector activation, Workspace tool policy) as configured at the time of the clone;
   the connector owns the git authentication. It is the platform's prepare action: the phase agent's own surface and
   capability (read-only at Clarify) are not touched. The clone's ``origin`` must be the run's repository on the host
   of the Workspace's **currently configured** connection (``agent_gateway.repository_root.run_repository_refusal``):
   a scope check now — not a pin of a connection or credential revision the run started with, which the run never
   recorded. A connection or repository binding that no longer matches is refused; it is re-confirmed by
   reconfiguring, never silently re-interpreted.
3. **The remote is what the run knows.** The run's branch must exist on the remote at the last head the run recorded
   (its last push ``head_sha``, else an adopted branch's head, else its base for a branch it created empty), and the
   run's base must be an ancestor of it. The copy is put on that head: never a second branch, never an adoption.
4. **Fresh target, proven before it is taken over.** The clone goes into a new run-owned folder
   (``<session workspace>/run-copies/<run>-<random>`` under the currently configured base); an existing folder —
   the recorded path or any other — is never reset, reused or overwritten (a recorded folder that is not empty and not
   a git working copy is refused). The candidate is prepared (branch and environment readiness) where it is; only when
   every proof holds is the run claimed again (``records.lock_run``) and its whole binding (:func:`run_binding`:
   status, node, entry, runtime target, main session, repository, branch, Workspace, requester, Work item, base, last
   known head, recorded copy) compared with the one taken before the clone. Any drift — stopped, moved on, switched to
   another runtime, re-bound, or re-created by a concurrent re-prepare — discards the candidate and adopts nothing. The
   callers (the Prepare step, "Change where the run executes") re-check the same binding (:func:`still_bound`) before
   they write any ready / not-ready report or pause, so a result never lands on a binding it was not made for. A
   repeat after success finds the copy and clones nothing.
5. **Only facts are recorded:** ``local_path``, head and base (``context.working_copy_recovery`` and the
   ``working_copy_recreated`` event); any failure text has URL user-info scrubbed.

Device and terminal runs prepare their own folder and never reach this module.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun, WorkflowRunEvent
from ....time_utils import utc_now
from .. import safe_git
from ..records import lock_run, main_session_id, record_event
from .origin_auth import origin_git_env

EVENT_RECREATED = "working_copy_recreated"
RECOVERY_KEY = "working_copy_recovery"
RECOVERY_DIR = "run-copies"
STATE_REFUSED = "refused"
STATE_UNVERIFIED = "recovery_unverified"
# Tools whose effect lives only in the working copy (or whose evidence is bound to its tree): a run whose phases used
# one may have lost local work with the copy.
LOCAL_WORK_TOOLS = frozenset({
    "write_workspace_file", "edit_workspace_file", "multi_edit_workspace_file", "apply_patch_workspace",
    "run_openrewrite_recipe", "bash", "run_cli_command", "run_validation_commands", "run_test_suite",
    "delegate_slices", "merge_slices",
})
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@")


def _scrubbed(text: str) -> str:
    """A failure text without any URL user-info (a token in a clone URL never reaches the run's record)."""
    return _URL_USERINFO.sub(r"\1***@", str(text or ""))


def _refused(detail: str, *, state: str = STATE_REFUSED) -> dict[str, Any]:
    """A preparation report the node's ``decide`` reads as not prepared (``branch.state`` is not ready)."""
    return {"branch": {"state": state, "detail": _scrubbed(detail)[:400]}, "runtime": "server"}


def _unverified(detail: str) -> dict[str, Any]:
    return _refused(f"{detail}; a person decides", state=STATE_UNVERIFIED)


async def _is_working_copy(root: Path) -> bool:
    return (await safe_git.git(root, "rev-parse", "--is-inside-work-tree"))[0] == 0


def _gone(root: Path) -> bool:
    return not root.exists() or (root.is_dir() and not any(root.iterdir()))


def _known_remote_head(context: dict[str, Any]) -> str:
    """The branch head the run last knew on the remote: its last push, an adopted head, else its base."""
    adoption = dict(context.get("branch_adoption") or {})
    return str(context.get("head_sha") or adoption.get("head") or context.get("base_sha") or "")


async def _possible_local_work(db: AsyncSession, run: WorkflowRun) -> str:
    """Why the lost copy may have held work the remote lacks (or tree-bound evidence), else ``''``."""
    from ..graph import NODE_PHASE, graph_for_run
    from ..phase_agents import phase_class
    from ..phase_workspace import READ_ONLY_CLASS
    from ..states import EVENT_NODE_ENTERED
    from ..test_runs import recorded_runs

    context = dict(run.context or {})
    graph = await graph_for_run(db, run)
    entered = (await db.execute(select(WorkflowRunEvent.node_id).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_NODE_ENTERED))).scalars().all()
    for node_id in sorted({str(item or "") for item in entered}):
        node = graph.nodes.get(node_id)
        if node is not None and node.kind == NODE_PHASE and phase_class(node.config) != READ_ONLY_CLASS:
            return f"the run entered the phase '{node_id}', which changes the repository"
    for node_id, recorded in sorted(dict(context.get("evidence") or {}).items()):
        used = {str(dict(item).get("name") or "") for item in dict(recorded or {}).get("tools") or []
                if isinstance(item, dict)}
        if used & LOCAL_WORK_TOOLS:
            return f"the phase '{node_id}' used {', '.join(sorted(used & LOCAL_WORK_TOOLS))} in the lost copy"
    if recorded_runs(run):
        return "the run recorded test runs on the lost copy"
    if context.get("review"):
        return "the run recorded an independent review of the lost copy"
    if context.get("slices"):
        return "the run delegated slices from the lost copy"
    return ""


async def _fresh_clone_root(db: AsyncSession, run: WorkflowRun) -> Path | None:
    """A new, empty, run-owned folder in the main session's workspace under the currently configured base."""
    from ...session.workspace import _build_session_workspace_root, get_session_workspace_base_dir

    session_id = await main_session_id(db, run)
    if not session_id or await db.get(Session, session_id) is None:
        return None
    session_root = _build_session_workspace_root(await get_session_workspace_base_dir(db), session_id)
    root = session_root / RECOVERY_DIR / f"{run.id[:8]}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=False)
    return root


async def _clone(db: AsyncSession, run: WorkflowRun, root: Path) -> tuple[str, str]:
    """``(local_path, '')`` from the governed prepare tool, or ``('', why)``."""
    from ..platform import dispatch
    from ..platform.repo_ref import TOOLS, parse_repository

    ref = parse_repository(run.repository)
    if ref is None:
        return "", "the run names no repository to clone"
    # The same governed dispatch as create_branch / checkout (identity, capability, approvals, connector, policy).
    outcome = await dispatch.dispatch_tool(db, run, TOOLS[ref.provider]["prepare"],
                                           {**ref.args(), "branch_name": run.branch}, capability_class="change",
                                           workspace_root=str(root))
    local_path = str(outcome.result.get("local_path") or "") if outcome.ok else ""
    if not local_path or not Path(local_path).resolve().is_relative_to(root):
        return "", f"the repository could not be cloned: {outcome.reason or 'no working copy in the run folder'}"
    return local_path, ""


async def _repository_refusal(db: AsyncSession, run: WorkflowRun, root: Path) -> str:
    """Why the clone is not the run's repository on the Workspace's connection, else ``''``."""
    from ...agent_gateway.repository_root import run_repository_refusal
    from ...knowledge.sources.repository_snapshot.remote import RemoteRefusedError, parse_remote

    code, url, _err = await safe_git.git(root, "remote", "get-url", "origin")
    try:
        refused = await run_repository_refusal(db, run, parse_remote(url.strip())) if code == 0 else True
    except RemoteRefusedError:
        refused = True
    return "" if refused is None else f"the clone is not provably the run's repository {run.repository}"


async def _on_remote_head(root: Path, branch: str, known: str, base_sha: str) -> tuple[str, str, bool]:
    """``(head, '', _)`` with the copy on the run's remote branch at the known head, or ``('', why, unverified)``."""
    remote = f"refs/remotes/origin/{branch}"
    code, remote_head, _err = await safe_git.git(root, "rev-parse", "--verify", "--quiet", remote)
    if code != 0:
        return "", f"the run's branch '{branch}' does not exist on the remote: nothing to re-create it from", False
    remote_head = remote_head.strip()
    if not known:
        return "", "the run records no head or base for its branch: the re-created copy cannot be verified", False
    if remote_head != known:
        return "", (f"the remote branch is at {remote_head[:12]}, not at {known[:12]} as the run last recorded "
                    "it"), True
    code, _out, err = await safe_git.git(root, "checkout", "-q", "-B", branch, remote)
    if code != 0:
        return "", f"the run's branch could not be checked out: {err.strip()[:200]}", False
    if not base_sha or (await safe_git.git(root, "merge-base", "--is-ancestor", base_sha, remote_head))[0] != 0:
        return "", f"the branch head {remote_head[:12]} does not descend from the run's base {base_sha[:12]}", False
    return remote_head, "", False


async def run_binding(db: AsyncSession, run: WorkflowRun, *, with_copy: bool = True) -> tuple[Any, ...]:
    """What a preparation is bound to: where the run stands, where it runs, and what it works on.

    Status, node, entry; the runtime target (kind, device, folder, profile, model) and the main session; repository,
    branch, Workspace, requester, Work item, base and the last known remote head; with ``with_copy`` the recorded
    working copy too. A preparation result is written, and a re-created copy taken over, only while this is unchanged.
    """
    from ..runtime_target.target import stored_target

    context = dict(run.context or {})
    target = stored_target(run) or {}
    where = tuple(str(target.get(key) or "") for key in ("kind", "device_id", "folder", "profile", "model"))
    binding = (run.status, run.current_node_id, dict(run.node_state or {}).get("entry"), where,
               await main_session_id(db, run), run.repository, run.branch, run.project_id, run.requested_by,
               run.work_item_id, str(context.get("base_sha") or ""), _known_remote_head(context))
    return (*binding, str(context.get("local_path") or "")) if with_copy else binding


async def still_bound(db: AsyncSession, run: WorkflowRun, binding: tuple[Any, ...], *, with_copy: bool = True) -> bool:
    """Claim the run (``records.lock_run``: a concurrent writer means a re-read) and compare its binding."""
    run = await lock_run(db, run)
    return await run_binding(db, run, with_copy=with_copy) == binding


def _discard(root: Path | None) -> None:
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


async def _recreate(db: AsyncSession, run: WorkflowRun, spec: dict[str, Any], recorded: str) -> dict[str, Any]:
    """The preparation report of a re-created copy, taken over only when every proof holds."""
    from .preparation import decide
    from .server_prepare import prepare_locally

    if not run.branch:
        return _refused("the run has no branch to re-create its working copy on")
    if lost := await _possible_local_work(db, run):
        return _unverified(f"the run's working copy is gone and {lost}: unpushed, uncommitted or tree-bound work "
                           "would not come back with a clone, so it is not re-created automatically")
    context = dict(run.context or {})
    stands = await run_binding(db, run)
    candidate_root = await _fresh_clone_root(db, run)
    if candidate_root is None:
        return _refused("the run has no session to hold its working copy")
    local_path, why = await _clone(db, run, candidate_root)
    if not why:
        why = await _repository_refusal(db, run, Path(local_path))
    head, unverified = "", False
    if not why:
        head, why, unverified = await _on_remote_head(Path(local_path), run.branch, _known_remote_head(context),
                                                      str(context.get("base_sha") or ""))
    if why:
        _discard(candidate_root)
        return _unverified(why) if unverified else _refused(why)
    # Branch and environment readiness of the candidate, fetched with the connection's Git auth.
    report = await prepare_locally(Path(local_path), spec, git_env=await origin_git_env(db, run, local_path))
    if not decide(report).ok:
        _discard(candidate_root)
        return report
    if not await still_bound(db, run, stands):
        # Stopped, moved on, switched to another runtime or re-bound, or re-created by a concurrent re-prepare:
        # nothing of this preparation is adopted.
        _discard(candidate_root)
        return _refused("the run changed while its working copy was being re-created; nothing was adopted")
    root = Path(local_path).resolve()
    recovery = {"previous_path": recorded, "local_path": str(root), "head": head,
                "base_sha": str(context.get("base_sha") or ""), "base_is_ancestor": True,
                "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), "local_path": str(root), RECOVERY_KEY: recovery}
    record_event(db, run, EVENT_RECREATED, node_id=run.current_node_id, detail=recovery)
    return report


async def _builds_or_tests(db: AsyncSession, run: WorkflowRun) -> bool:
    """Whether the run's workflow has a step that builds or tests (``server_build.builds_or_tests``): only then does
    the server prepare its test environment."""
    from ..runtime_target.server_build import builds_or_tests, run_definition

    definition = await run_definition(db, run)
    return builds_or_tests(definition)


async def prepare_on_server(db: AsyncSession, run: WorkflowRun, spec: dict[str, Any]) -> dict[str, Any] | None:
    """The server preparation report of the run's folder; ``None`` when the run has no folder to prepare. Its
    commands are audited as the run requester's (``command_audit.run_actor``)."""
    from ...execution_runtime.command_audit import run_actor

    with run_actor(db, run, tool_name="workspace.prepare"):
        return await _prepare_on_server(db, run, spec)


async def _prepare_on_server(db: AsyncSession, run: WorkflowRun, spec: dict[str, Any]) -> dict[str, Any] | None:
    from ..test_runs import working_copy_root
    from .server_prepare import prepare_locally

    spec = {**dict(spec or {}), "run_id": run.id,  # the run's work in progress is restored after the branch
            "environment_needed": await _builds_or_tests(db, run)}
    recorded = str(dict(run.context or {}).get("local_path") or "")
    if not recorded:
        root = await working_copy_root(db, run)  # no copy was ever recorded: the prepare works
        if root is None:
            return None
        return await prepare_locally(root, spec, git_env=await origin_git_env(db, run, root))
    root = Path(recorded).expanduser().resolve()
    if not _gone(root):
        if root.is_dir() and await _is_working_copy(root):
            # The fetches from origin carry the connection's Git auth (private Data Center repositories).
            return await prepare_locally(root, spec, git_env=await origin_git_env(db, run, root))
        return _refused("the run's recorded working-copy folder exists but is not a git working copy; it is never "
                        "overwritten")
    return await _recreate(db, run, spec, recorded)


__all__ = ["EVENT_RECREATED", "LOCAL_WORK_TOOLS", "RECOVERY_KEY", "STATE_UNVERIFIED", "prepare_on_server",
           "run_binding", "still_bound"]
