"""The agent board for a run-bound octryx-claude session without ``work:manage`` (teamwork design, section 5).

The board tools (``mcp_agent_board_tools``) run under ``work:manage``. A device job's grant never holds it
(``devices/contract.DEVICE_JOB_SCOPES``), yet team delivery depends on the board: an item that cannot go on asks its
coordinator (``board_post``), the coordinator's board wake reads and answers (``board_read``, ``board_post
reply_to``), both acknowledge (``board_ack``). Under ``work:manage`` alone every
board_read and board_post of a team item is refused "OAuth grant lacks required scope:
work:manage", so a blocked item could reach nobody.

Least privilege, as for the run's Work item (``mcp_run_work_item``): the workflow run is the authority, and only for
its own board:

- the scope ``workflow:read`` (board_read) or ``workflow:execute`` (board_post, board_ack);
- the connection's launcher session (``X-Octryx-Session``) is the caller's and follows an active run;
- the user may still act on that run (``run_access`` "write");
- the Workspace is the run's only (never every Workspace the user belongs to);
- a post (a reply too) is on the run's Work item (its id or key, or none given; any other item is refused), and a
  reply only answers a message of the run's Workspace;
- a read that is not ``addressed_to_me`` sees only the run's Work item's thread.

A grant with ``work:manage`` keeps the normal path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Session, User, WorkItem
from .mcp_work_access import WorkGrantScope

RUN_BOARD_READ_SCOPE = "workflow:read"
RUN_BOARD_WRITE_SCOPE = "workflow:execute"
REFUSED_DETAIL = ("OAuth grant lacks required scope: work:manage (without it, only the board of this session's "
                  "workflow run is reachable)")
NOT_RUN_ITEM_DETAIL = "Without work:manage the board names only this workflow run's Work item"


def run_board_tool(tool_name: str, scopes: tuple[str, ...] | frozenset[str] | list[str]) -> bool:
    """Whether a grant without ``work:manage`` may try ``tool_name`` on its run's board."""
    from .mcp_agent_board_tools import ACK_TOOL, POST_TOOL, READ_TOOL

    if tool_name == READ_TOOL:
        return RUN_BOARD_READ_SCOPE in scopes
    return tool_name in (POST_TOOL, ACK_TOOL) and RUN_BOARD_WRITE_SCOPE in scopes


async def _run_of_header(db: AsyncSession, user: User, headers: Mapping[str, str]) -> Any:
    """The active run the call's launcher session follows, when the session is the caller's own."""
    import uuid

    from .agent_gateway.contract import EXTERNAL_AGENT_TYPE, HEADER_SESSION, SESSION_KEY_METADATA
    from .workflow_runs.records import active_run_for_session

    try:
        key = str(uuid.UUID(str(headers.get(HEADER_SESSION) or "").strip()))
    except ValueError:
        return None
    rows = (await db.execute(select(Session).where(
        Session.agent_type == EXTERNAL_AGENT_TYPE, Session.user_id == user.id,
        Session.metadata_[SESSION_KEY_METADATA].as_string() == key))).scalars().all()
    for session in rows:
        run = await active_run_for_session(db, session.id)
        if run is not None and run.project_id == session.project_id:
            return run
    return None


async def run_board_scope(db: AsyncSession, *, user: User, grant_id: str | None,
                          headers: Mapping[str, str]) -> tuple[WorkGrantScope, Any]:
    """``(scope, run)``: the run's Workspace as the whole board scope; 403 for a session that follows no run."""
    from .mcp_work_access import resolve_work_grant_binding
    from .workflow_runs.access import run_access

    binding = await resolve_work_grant_binding(db, grant_id=grant_id, user_id=user.id)  # a valid, own grant
    run = await _run_of_header(db, user, headers)
    if run is None or not run.project_id or await run_access(db, run, user) != "write":
        raise HTTPException(status_code=403, detail=REFUSED_DETAIL)
    if binding is not None and run.project_id not in binding:
        raise HTTPException(status_code=403, detail=REFUSED_DETAIL)
    workspace = frozenset({run.project_id})
    return WorkGrantScope(grant_id=grant_id, binding=binding, item_project_ids=workspace,
                          listing_project_ids=workspace), run


async def _run_item_id(db: AsyncSession, run: Any, value: Any) -> str:
    """The run's Work item id for ``value`` (its id or key; empty: the run's); 403 for any other item."""
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    text = str(value or "").strip()
    if item is None:
        if text:
            raise HTTPException(status_code=403, detail=NOT_RUN_ITEM_DETAIL)
        return ""
    if text and text not in (item.id, item.source_key, run.ticket_key or item.id):
        raise HTTPException(status_code=403, detail=NOT_RUN_ITEM_DETAIL)
    return item.id


def run_board_handlers(handlers: Mapping[str, Any], run_of: Any) -> dict[str, Any]:
    """The board handlers narrowed to the run's Work item (see the module docstring); ``run_of()`` is the run
    :func:`run_board_scope` resolved for this call."""
    from .mcp_agent_board_tools import POST_TOOL, READ_TOOL

    def narrowed(name: str, handler: Any) -> Any:
        async def call(db: AsyncSession, *, user: Any, scope: Any, arguments: dict[str, Any]) -> dict[str, Any]:
            run = run_of()
            arguments = {**arguments, "project_id": run.project_id}
            if name == POST_TOOL:  # a reply too: the run's thread holds the answer
                arguments["work_item_id"] = await _run_item_id(db, run, arguments.get("work_item_id")) or None
            elif name == READ_TOOL and (arguments.get("work_item_id") or not arguments.get("addressed_to_me")):
                arguments["work_item_id"] = await _run_item_id(db, run, arguments.get("work_item_id")) or None
            return await handler(db, user=user, scope=scope, arguments=arguments)

        return call

    return {name: narrowed(name, handler) for name, handler in handlers.items()}


__all__ = ["REFUSED_DETAIL", "run_board_handlers", "run_board_scope", "run_board_tool"]
