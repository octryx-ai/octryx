"""The calling session of an MCP workflow run tool and the run contract it sees.

Shared by the workflow run tools (``mcp_workflow_run_tools``) and the chat side
(``mcp_workflow_run_chat``): a launcher session or a platform chat is the gateway a
run binds to, and every answer carries the run contract as that session sees it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, User, WorkflowRun
from .knowledge.sources.repository_snapshot.session_target import bound_gateway_session
from .mcp_governed_knowledge import McpCaller
from .workflow_runs.octryx.compact_view import compact
from .workflow_runs.octryx.contract import run_contract
from .workflow_runs.records import WorkflowRunError

_NO_LAUNCHER = {"state": "needs_configuration", "reason": "octryx_session_required",
                "message": "A workflow run binds to an octryx-claude session; start one with octryx-claude."}


def _refusal(error: WorkflowRunError) -> dict[str, Any]:
    state = error.state or ("denied" if error.status_code in (401, 403) else "not_found"
                            if error.status_code == 404 else "invalid_request")
    return {"state": state, "reason": error.code, "message": str(error)}


async def _gateway(db: AsyncSession, caller: McpCaller, user: User, workspace_id: str):
    if caller.chat_session_id:
        chat = await db.get(Session, caller.chat_session_id)
        owned = chat is not None and chat.user_id == user.id and chat.project_id == workspace_id
        return chat if owned else None
    if not caller.session_key:
        return None
    return await bound_gateway_session(db, user_id=user.id, workspace_id=workspace_id, session_key=caller.session_key)


async def _contract(db: AsyncSession, run: WorkflowRun, user: User, gateway: Session | None) -> dict[str, Any]:
    """The run contract as ``gateway`` (the calling session) sees it.

    A teamwork item's session works under its item's phase and the coordinator's board wake under its plan phase
    (``run_contract(session=...)``), while the run itself stands at the ``parallel_work`` node, which is no phase.
    Without the session the hooks see the item's phase but these MCP tools do not: workflow_run_status answers
    ``phase: null`` and every submit_phase_result is refused ``outside_phase_tools`` while the item's Stop keeps asking
    for it, until the run pauses on its loop limit.
    """
    return await run_contract(db, run, principal=user, session=gateway)


def _view(contract: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """The compact contract unless the call asks for ``detail`` (``compact_view``)."""
    return contract if arguments.get("detail") is True else compact(contract)
