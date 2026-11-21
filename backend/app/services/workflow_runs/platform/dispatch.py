"""Dispatch one governed tool for a run, and read its outcome as a closed state.

``succeeded`` | ``failed`` (with a reason) | ``approval_pending`` (the tool approval gate filed an approval in the
run's chat session: the run waits for it; once granted the same call runs again and consumes the grant).

A failure carries its **failure class** (``action_failures`` decides what is recoverable), read only from structured
facts: the provider's HTTP ``status_code``, the closed tool ``status`` vocabulary, the exception type of a tool that
raised. A tool failure without such a fact is ``external`` (the provider refused); a handler's own precondition
failure names its class explicitly, else it is ``invalid`` (retrying cannot change it).

**The run's root** (:func:`run_root`; otherwise a push refused "local_path must stay inside workspace root"
because it got the chat session's folder while the run's copy had been re-created under another base). A run's
action dispatches in the same root its phase turns work in — the run's working copy
(``phase_workspace.run_working_copy``, from ``run.context.local_path``), never the chat session's folder:

- an explicit ``workspace_root`` (the folder a copy is being cloned into, ``recovery``; the copy just prepared,
  ``branch_fast_forward``) is used as given;
- a call that prepares a copy (a provider's prepare tool, ``scm.TOOLS[...]["prepare"]``) gets the session's folder,
  where copies are established;
- otherwise a run with a working copy dispatches in it, so a tool's "path inside the workspace root" check is made
  against the run's copy;
- a call that works in the copy (a ``local_path`` argument) refuses ``not_configured`` when the run's copy is missing
  or the path is outside it — never a fallback to another folder.

An API-only action (pull request, CI, Jira, Confluence) of a run without a copy keeps the session's folder (it reads
no file). Tool use outside runs is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ....tools.context import ToolContext
from ...project.service import get_project_config
from ...run_capability.declared import SOURCE_FLOW_DEFINITION, declared_run_capability
from ..phase_workspace import RECREATE_ACTION, run_working_copy
from ..records import main_session_id

SUCCEEDED = "succeeded"
FAILED = "failed"
APPROVAL_PENDING = "approval_pending"
_FAILED_STATUSES = frozenset({"error", "failed", "denied", "blocked", "refused", "timeout"})

# Failure classes (closed): the first five are recoverable by a person (``action_failures.RECOVERABLE``).
CLASS_ALREADY_EXISTS = "already_exists"
CLASS_NOT_CONFIGURED = "not_configured"
CLASS_PERMISSION = "permission"
CLASS_TRANSIENT = "transient"
CLASS_EXTERNAL = "external"
CLASS_BRANCH_CONFLICT = "branch_conflict"
CLASS_PR_CONFLICT = "pr_conflict"
CLASS_INVALID = "invalid"
CLASS_SAFETY = "safety"
CLASS_REJECTED = "rejected"
# Workspace preparation (``workspace/preparation``): the runtime's test environment, or foreign uncommitted changes.
CLASS_ENVIRONMENT_NOT_READY = "environment_not_ready"
CLASS_WORKSPACE_DIRTY = "workspace_dirty"
# A push with nothing new while the pushed commit's CI failed: back to the fix phase (``ci_return``), no pause.
CLASS_NEEDS_FIX = "needs_fix"
# A write-back definition of another Workspace than the Work item's: a configuration error, never retried.
CLASS_SCOPE_MISMATCH = "scope_mismatch"
# "environment": the platform's own disk or runtime (``connectors.git_errors`` disk), never the service's.
_STATUS_CLASSES = {"timeout": CLASS_TRANSIENT, "denied": CLASS_PERMISSION, "refused": CLASS_PERMISSION,
                   "environment": CLASS_ENVIRONMENT_NOT_READY}
COPY_MISSING_REASON = (f"this action works in the run's working copy, which is missing on the server. {RECREATE_ACTION}"
                       ": the platform re-creates it from the run's repository and branch; then retry the action")
NO_COPY_REASON = ("this action works in the run's working copy, but the run has none on the server (it was never "
                  "prepared there); create the run's branch on the server first")


def class_of_status_code(code: Any) -> str:
    """The failure class an HTTP status names ('' when it names none)."""
    if type(code) is not int or code < 400:
        return ""
    if code in (401, 403):
        return CLASS_PERMISSION
    if code == 404:
        return CLASS_NOT_CONFIGURED
    if code == 409:
        return CLASS_ALREADY_EXISTS
    if code in (408, 425, 429) or code >= 500:
        return CLASS_TRANSIENT
    return CLASS_EXTERNAL


def class_of_exception(error: BaseException) -> str:
    if isinstance(error, TimeoutError | ConnectionError):
        return CLASS_TRANSIENT
    if isinstance(error, PermissionError):
        return CLASS_PERMISSION
    return CLASS_EXTERNAL


@dataclass(slots=True)
class ToolOutcome:
    state: str
    result: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    approval_id: str | None = None
    failure_class: str = ""

    @property
    def ok(self) -> bool:
        return self.state == SUCCEEDED


def read_outcome(result: Any) -> ToolOutcome:
    payload = result if isinstance(result, dict) else {"result": result}
    if payload.get("approval_required") and payload.get("approval_id") and payload.get("approval_status") == "pending":
        return ToolOutcome(APPROVAL_PENDING, payload, "waits for the tool approval", str(payload["approval_id"]))
    status = str(payload.get("status") or "").strip().lower()
    failure_class = class_of_status_code(payload.get("status_code")) or _STATUS_CLASSES.get(status, CLASS_EXTERNAL)
    if payload.get("error"):
        error = payload["error"]
        text = error.get("message") if isinstance(error, dict) else error
        return ToolOutcome(FAILED, payload, str(text or "the tool failed")[:500], failure_class=failure_class)
    if status in _FAILED_STATUSES:
        return ToolOutcome(FAILED, payload, f"status {status}", failure_class=failure_class)
    return ToolOutcome(SUCCEEDED, payload)


def run_root(run: WorkflowRun, tool: str, arguments: dict[str, Any]) -> tuple[str | None, str]:
    """``(root, '')``: the run's working copy, or ``None`` for the session's folder; ``('', why)`` refuses."""
    from .repo_ref import TOOLS

    prepares_copy = tool in {tools["prepare"] for tools in TOOLS.values()}
    copy = None if prepares_copy else run_working_copy(run)
    local_path = str(arguments.get("local_path") or "").strip()
    if local_path and not prepares_copy:
        if copy is None:
            return "", COPY_MISSING_REASON if dict(run.context or {}).get("local_path") else NO_COPY_REASON
        if not Path(local_path).expanduser().resolve().is_relative_to(copy):
            return "", f"local_path must stay inside the run's working copy: {copy}"
    return (str(copy) if copy is not None else None), ""


async def tool_context(db: AsyncSession, run: WorkflowRun, capability_class: str, *,
                       workspace_root: str | None = None, typed_action: bool = True) -> ToolContext:
    """The context a run's platform action dispatches in: the requester, the run's session and the given root (the
    session's workspace when ``None``). ``typed_action``: a platform catalog action (its tool is fixed by the platform),
    which the published workflow explicitly allows; a free ``tool`` step of a definition is not (review of)."""
    from ...session.workspace import resolve_session_workspace_root

    session_id = await main_session_id(db, run)
    session = await db.get(Session, session_id) if session_id else None
    if workspace_root is None and session is not None:
        workspace_root = str(await resolve_session_workspace_root(db, session))
    capability = declared_run_capability(capability_class, source=SOURCE_FLOW_DEFINITION)
    return ToolContext(
        user_id=run.requested_by, project_ids=[run.project_id] if run.project_id else [], roles=[],
        session_id=session_id, project_config=await get_project_config(run.project_id, db), db=db,
        run_capability=capability.tool_context_state(), workspace_root=workspace_root,
        workflow_platform_action=typed_action,
    )


async def dispatch_tool(
    db: AsyncSession, run: WorkflowRun, tool: str, arguments: dict[str, Any], *, capability_class: str,
    workspace_root: str | None = None, typed_action: bool = True,
) -> ToolOutcome:
    from ....tools.registry import execute_tool_with_plugins
    from ..handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)

    if workspace_root is None:
        workspace_root, refused = run_root(run, tool, arguments)
        if refused:
            return ToolOutcome(FAILED, {}, refused, failure_class=CLASS_NOT_CONFIGURED)
    context = await tool_context(db, run, capability_class, workspace_root=workspace_root, typed_action=typed_action)
    try:
        from ...content_security.knowledge_fence import unfenced_result

        # A platform action keeps the system's own text (Work items, PR titles); the fence is for models only.
        return read_outcome(unfenced_result(await execute_tool_with_plugins(tool, arguments, context)))
    except Exception as error:  # a tool that raises is a failed step, recorded with its reason
        return ToolOutcome(FAILED, {}, f"{type(error).__name__}: {error}"[:500],
                           failure_class=class_of_exception(error))


__all__ = ["APPROVAL_PENDING", "FAILED", "SUCCEEDED", "ToolOutcome", "class_of_exception", "class_of_status_code",
           "dispatch_tool", "read_outcome", "run_root", "tool_context"]
