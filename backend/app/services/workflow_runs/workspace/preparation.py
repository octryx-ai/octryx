"""``workspace.prepare``: the run's working folder is on its branch and can run the repository's tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ....time_utils import utc_now
from ..graph import FAILED, SUCCEEDED, PhasedNode
from ..platform.dispatch import (
    CLASS_ENVIRONMENT_NOT_READY,
    CLASS_INVALID,
    CLASS_NOT_CONFIGURED,
    CLASS_TRANSIENT,
    CLASS_WORKSPACE_DIRTY,
    ToolOutcome,
)
from ..records import record_event
from .server_prepare import READY_BRANCH_STATES

CONTEXT_KEY = "workspace_preparation"
RUNTIME_SERVER, RUNTIME_DEVICE, RUNTIME_TERMINAL = "server", "device", "terminal"
STATE_PENDING, STATE_READY, STATE_NOT_READY = "pending", "ready", "not_ready"
ACTION = "workspace.prepare"
EVENT_REPORTED = "workspace_preparation_reported"
MAX_REPORT_TEXT = 2000


def preparation(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def _set(run: WorkflowRun, value: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), CONTEXT_KEY: value}


async def runtime_of(db: AsyncSession, run: WorkflowRun) -> str:
    from ..octryx.continuation_marker import _device_target
    from ..runtime_target.target import stored_target

    if (target := stored_target(run)) is not None:
        return str(target["kind"])
    from ..records import main_session_id
    from ..test_runs import device_run

    thread_id = await main_session_id(db, run)
    if _device_target(await db.get(Session, thread_id) if thread_id else None) is not None:
        return RUNTIME_DEVICE
    return RUNTIME_TERMINAL if await device_run(db, run) else RUNTIME_SERVER


async def requirement(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    from ...agent_gateway.git_upload import git_path, working_copy
    from .spec import environment_for_run, expected_repository, runtime_environment

    context = dict(run.context or {})
    head = str(dict(context.get("branch_adoption") or {}).get("head") or context.get("base_sha") or "")
    repository = await expected_repository(db, run)
    if repository is not None and (remote := await _server_remote(context)):
        repository = {**repository, "remote_url": remote}
    # A launcher without git credentials (a server runner) reads the branch through the platform's working copy.
    gateway = git_path(run.id) if repository is not None and working_copy(run)[0] is not None else None
    return {"branch": run.branch or "", "head": head[:64] or None, "repository": repository,
            "environment": runtime_environment(await environment_for_run(db, run)), "git_gateway": gateway}


async def _server_remote(context: dict[str, Any]) -> str:
    from pathlib import Path
    from urllib.parse import urlsplit, urlunsplit

    from ..safe_git import git

    local = str(context.get("local_path") or "")
    if not local or not (Path(local) / ".git").exists():
        return ""
    code, out, _err = await git(Path(local), "remote", "get-url", "origin")
    url = out.strip() if code == 0 else ""
    if "://" not in url:
        return ""  # a local path or scp form is nothing a device can use
    parts = urlsplit(url)
    netloc = f"{parts.hostname}:{parts.port}" if parts.port else str(parts.hostname or "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", "")) if netloc else ""


def decide(report: dict[str, Any]) -> ToolOutcome:
    branch = dict(report.get("branch") or {})
    environment = dict(report.get("environment") or {})
    facts = {"branch": branch, "environment": environment, "root": report.get("root"), "runtime": report.get("runtime")}
    if branch.get("state") == "dirty":
        files = ", ".join(str(item) for item in list(branch.get("dirty_files") or [])[:5])
        return ToolOutcome(FAILED, facts, f"{branch.get('detail') or 'uncommitted changes'} ({files}); commit or stash "
                                          f"them, then retry", failure_class=CLASS_WORKSPACE_DIRTY)
    if branch.get("state") not in READY_BRANCH_STATES:  # ``empty_repository``: the first commit starts the branch
        return ToolOutcome(FAILED, facts, f"the run's branch could not be checked out: {branch.get('detail') or ''}",
                           failure_class=CLASS_TRANSIENT if branch.get("state") == "unavailable" else CLASS_INVALID)
    probes = list(environment.get("probes") or [])
    if environment.get("state") in ("not_declared", "environment_file", "not_needed"):
        # ``environment_file``: the repository's own file (read in the folder, its setup run when it is there); the
        # pipeline judges it and sends a missing or invalid file back to the agent, so it never pauses the run here.
        # ``not_needed``: a server run of a workflow that neither builds nor tests (``server_prepare``).
        return ToolOutcome(SUCCEEDED, facts)  # nothing to verify; the test command's own outcome stays the backstop
    if environment.get("state") != STATE_READY or not probes or not all(dict(item).get("ok") for item in probes):
        reason = str(environment.get("reason") or "a readiness probe failed")[:MAX_REPORT_TEXT]
        return ToolOutcome(FAILED, facts, reason, failure_class=CLASS_ENVIRONMENT_NOT_READY)
    return ToolOutcome(SUCCEEDED, facts)


def _proposal_note(spec: dict[str, Any]) -> str:
    proposal = dict(dict(spec.get("environment") or {}).get("proposal") or {})
    if not proposal:
        return ""
    return (f" Proposed from {proposal.get('derived_from')}: setup {proposal.get('setup')}, test "
            f"'{proposal.get('test')}', lint '{proposal.get('lint') or ''}', path {proposal.get('path')} — declare it "
            "as the repository's environment (Workspace → repositories → coding setup), then retry.")


def _with_proposal(outcome: ToolOutcome, spec: dict[str, Any]) -> ToolOutcome:
    if outcome.failure_class != CLASS_ENVIRONMENT_NOT_READY:
        return outcome
    return ToolOutcome(outcome.state, outcome.result, (outcome.reason + _proposal_note(spec))[:MAX_REPORT_TEXT],
                       failure_class=outcome.failure_class)


async def prepare_workspace(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> tuple[ToolOutcome, str]:
    from ..platform_actions import WAIT

    if not run.branch:
        return ToolOutcome(FAILED, reason="the run has no branch to prepare (create it first)",
                           failure_class=CLASS_INVALID), FAILED
    from .app_choice import paused_for_app

    if await paused_for_app(db, run, node):
        return ToolOutcome("waiting", {"needs_input": "app"}), WAIT
    spec = await requirement(db, run)
    runtime = await runtime_of(db, run)
    entry = dict(run.node_state or {}).get("entry")
    if runtime == RUNTIME_SERVER:
        from .recovery import prepare_on_server, run_binding, still_bound

        binding = await run_binding(db, run, with_copy=False)
        # A recorded copy that is gone (a recreated container) is re-created first, only when that is provable.
        report = await prepare_on_server(db, run, spec)
        if not await still_bound(db, run, binding, with_copy=False):
            # The run moved, stopped or was switched meanwhile: nothing is recorded or routed for this node entry.
            return ToolOutcome("waiting", {"superseded": True}), WAIT
        if report is None:
            return ToolOutcome(FAILED, reason="the run has no working copy to prepare",
                               failure_class=CLASS_INVALID), FAILED
        outcome = _with_proposal(decide(report), spec)
        _set(run, {"state": STATE_READY if outcome.ok else STATE_NOT_READY, "runtime": runtime, "node_id": node.id,
                   "entry": entry, "spec": spec, "report": report, "at": utc_now().isoformat()})
        return outcome, SUCCEEDED if outcome.ok else FAILED
    _set(run, {"state": STATE_PENDING, "runtime": runtime, "node_id": node.id, "entry": entry, "spec": spec,
               "at": utc_now().isoformat()})
    from ..octryx.continuation import runtime_step_entered

    await runtime_step_entered(db, run, node)
    return ToolOutcome("waiting", {"runtime": runtime}), WAIT


async def record_report(db: AsyncSession, run: WorkflowRun, report: dict[str, Any], *, session_id: str) -> str:
    from ..graph import NODE_PHASE, graph_for_run
    from ..states import STATUS_RUNNING

    current = preparation(run)
    spec = dict(current.get("spec") or {})
    outcome = await _foreign_repository(db, run, report) or _with_proposal(decide(report), spec)
    state = STATE_READY if outcome.ok else STATE_NOT_READY
    entry = dict(run.node_state or {}).get("entry")
    # ``in_place``: a runtime switch prepares the new runtime at the run's current node, which it never routes.
    in_place = bool(current.get("in_place"))
    pending = (current.get("state") == STATE_PENDING and run.status == STATUS_RUNNING and not in_place
               and (current.get("node_id"), current.get("entry")) == (run.current_node_id, entry)
               and (report.get("node_id"), report.get("entry")) == (run.current_node_id, entry))
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={
        "state": state, "session_id": session_id, "runtime": report.get("runtime"), "for_node": pending,
        "branch": dict(report.get("branch") or {}).get("state"), "reason": outcome.reason[:500] or None})
    from ..wip_reset import EVENT_DONE, reset_reported

    if (done := reset_reported(run, report)) is not None:
        record_event(db, run, EVENT_DONE, node_id=run.current_node_id, detail={
            "sha": done.get("sha"), "files": done.get("files"), "backup": done.get("backup")})
    from .contract_pin import from_preparation
    from .run_app import remember_apps

    await from_preparation(db, run, report)
    await remember_apps(db, run, report)
    settled = pending or in_place or current.get("state") != STATE_PENDING
    _set(run, {**current, "state": state if settled else STATE_PENDING,
               "report": _bounded(report), "reported_by": session_id, "at": utc_now().isoformat()})
    if pending:
        await _route(db, run, outcome)
        return state
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if not outcome.ok and run.status == STATUS_RUNNING and node is not None and node.kind == NODE_PHASE:
        from .readiness import pause_not_ready

        await pause_not_ready(db, run, {"kind": outcome.failure_class, "reason": outcome.reason,
                                        "source": "workspace_preparation", "session_id": session_id})
    return state


async def _foreign_repository(db: AsyncSession, run: WorkflowRun, report: dict[str, Any]) -> ToolOutcome | None:
    from ...agent_gateway.repository_root import REASON_NOT_RUN_REPOSITORY, run_repository_refusal
    from ...knowledge.sources.repository_snapshot.remote import RemoteRefusedError, parse_remote

    branch = dict(report.get("branch") or {})
    if branch.get("state") == "foreign":
        return ToolOutcome(FAILED, {"branch": branch}, f"the folder is not the run's repository: "
                                                       f"{branch.get('detail') or ''}",
                           failure_class=CLASS_NOT_CONFIGURED)
    if not report.get("remote_url"):
        return None
    try:
        refused = await run_repository_refusal(db, run, parse_remote(report["remote_url"]))
    except RemoteRefusedError:
        refused = None
    if refused is None or refused.reason != REASON_NOT_RUN_REPOSITORY:
        return None  # an unverifiable run repository is refused when the session binds its folder
    # Recoverable: the requester switches the run to the right folder (``change_runtime``) and retries.
    return ToolOutcome(FAILED, {"branch": branch}, f"the folder {report.get('root') or ''} is not the run's "
                                                   f"repository {run.repository}", failure_class=CLASS_NOT_CONFIGURED)


async def _route(db: AsyncSession, run: WorkflowRun, outcome: ToolOutcome) -> None:
    from ..action_failures import record_failure
    from ..engine import resolve_current_node
    from ..engine_context import _set_context
    from ..states import EVENT_ACTION

    node_id = run.current_node_id or ""
    route = SUCCEEDED if outcome.ok else FAILED
    if not outcome.ok:
        record_failure(run, node_id=node_id, action=ACTION, reason=outcome.reason,
                       failure_class=outcome.failure_class or CLASS_INVALID)
    _set_context(run, "actions", node_id, {"action": ACTION, "result": route, "reason": outcome.reason or None,
                                           **({"failure_class": outcome.failure_class} if not outcome.ok else {})})
    _set_context(run, "action_ledger", f"{node_id}#{dict(run.node_state or {}).get('entry') or 0}",
                 {"action": ACTION, "result": route})
    record_event(db, run, EVENT_ACTION, node_id=node_id,
                 detail={"action": ACTION, "result": route, "reason": outcome.reason or None})
    await resolve_current_node(db, run, route, actor_id=None)


def _bounded(report: dict[str, Any]) -> dict[str, Any]:
    import json

    text = json.dumps(report, default=str)
    return report if len(text) <= 20_000 else {"truncated": True, "branch": report.get("branch"),
                                               "environment": {"state": dict(report.get("environment") or {})
                                                               .get("state")}}


def contract_view(run: WorkflowRun) -> dict[str, Any] | None:
    from .contract_pin import view as pin_view

    current = preparation(run)
    if not current:
        return None
    spec = dict(current.get("spec") or {})
    return {"state": current.get("state"), "runtime": current.get("runtime"), "node_id": current.get("node_id"),
            "entry": current.get("entry"), "branch": spec.get("branch"), "head": spec.get("head"),
            "repository": spec.get("repository"), "git_gateway": spec.get("git_gateway"),
            "environment": _with_pin(file_commands(spec.get("environment"), dict(current.get("report") or {}), run),
                                     run),
            **({"reset_to_wip": reset} if (reset := _pending_reset(run)) else {}),
            **({"environment_pin": pinned} if (pinned := pin_view(run)) else {})}


def _with_pin(environment: Any, run: WorkflowRun) -> Any:
    from .contract_pin import view

    pinned = view(run)
    if not isinstance(environment, dict) or not environment.get("environment_file") or not pinned:
        return environment
    return {**environment, "environment_pin": pinned}


def _pending_reset(run: WorkflowRun) -> str:
    from ..wip_reset import pending_reset

    return pending_reset(run)


def file_commands(environment: Any, report: dict[str, Any], run: Any = None) -> Any:
    from .spec import SOURCE_ENVIRONMENT_FILE, validate_environment

    if not isinstance(environment, dict) or environment.get("source") != SOURCE_ENVIRONMENT_FILE:
        return environment
    from .contract_pin import commands as pinned_commands

    # The pinned contract's commands (``contract_pin``), never a later account of a rewritten file.
    pinned = pinned_commands(run) if run is not None else None
    reported = pinned if pinned is not None else dict(
        dict(dict(report.get("environment") or {}).get("environment_file") or {}).get("commands") or {})
    raw = {key: str(reported.get(key) or "") for key in ("test", "lint", "system_test") if reported.get(key)}
    if not raw:
        return environment
    validated, errors = validate_environment(raw)
    if errors or not validated:
        return environment
    return {**environment, **{key: validated[key] for key in raw if validated.get(key)}}


__all__ = ["ACTION", "CONTEXT_KEY", "contract_view", "decide", "prepare_workspace", "preparation", "record_report",
           "requirement", "runtime_of"]
