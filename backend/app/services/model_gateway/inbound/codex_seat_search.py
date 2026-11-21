"""Codex's standalone web search on the person's seat, from the device.

The gpt-6 models run in Codex as Responses Lite, which never offers the provider-hosted ``web_search``
(codex-rs ``core/src/tools/spec_plan.rs``). Codex's search for them is the standalone tool ``web.run``, offered for a
custom provider only with ``supports_standalone_web_search = true`` (``ext/web-search``) and executed by Codex itself
as ``POST <base_url>/alpha/search``. With the seat's traffic on the device, ``<base_url>`` is the launcher's loopback
seat proxy, which sends the search to ChatGPT with the person's own login, like a ``/responses`` call:

1. ``POST /api/v1/model-gateway/openai/seat/search-admit`` with Codex's search request: the seat identity, session,
   Codex seat decision and engine as for ``/seat/admit``; then where the Workspace allows web search
   (``device_runs.tool_defaults.web_tools``; ``research_only``: ``device_runs.research_phases``). Admitted: a tool
   call ``codex_web_run`` with the request's
   commands (queries, opened URLs; bounded) is recorded as pending and its id is the ticket;
2. the proxy sends the request to ``https://chatgpt.com/backend-api/codex/alpha/search`` and streams the answer back;
3. ``POST .../seat/search-report`` with the ticket and the answer's status: the tool call becomes ``success`` (2xx) or
   ``error``. A completed search counts as ``web_search`` evidence of the phase (``octryx.stop.phase_evidence``).

A ticket is the session's own and used once; anything else is refused and writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ToolCall
from ....time_utils import utc_now
from ...agent_gateway.contract import STATE_DENIED, TOOL_CALL_SOURCE_GATEWAY
from .codex_seat import _codex_seat_context, codex_seat_refused
from .refusals import refusal

SEARCH_TOOL = "codex_web_run"
REASON_NOT_RESEARCH = "seat_search_not_research_phase"
REASON_SEARCH_INVALID = "seat_search_invalid"
REASON_TICKET_INVALID = "seat_search_ticket_invalid"
MAX_SEARCH_BODY = 2 * 1024 * 1024
MAX_RECORDED_COMMANDS_CHARS = 4_000


async def _json_body(request: Request) -> dict[str, Any] | None:
    raw = await request.body()
    if len(raw) > MAX_SEARCH_BODY:
        return None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _commands(body: Mapping[str, Any]) -> list[Any] | None:
    commands = body.get("commands")
    return commands if isinstance(commands, list) and commands else None


async def _search_allowed(db: AsyncSession, session: Any) -> tuple[bool, Any]:
    """``(allowed, run)``: the Workspace's ``tool_defaults.web_tools`` (``all`` by default, every
    phase and chat; ``research_only``: a research phase of the session's run; ``off``: never)."""
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import device_runs_section, tool_defaults
    from ...workflow_runs.octryx.research import research_min_sources
    from ...workflow_runs.octryx.subagents import turn_phase
    from ...workflow_runs.records import active_run_for_session

    loaded = await load_workspace_policy(db, session.project_id) if session.project_id else None
    raw = loaded.policy.raw if loaded is not None and loaded.policy is not None else {}
    mode = tool_defaults(device_runs_section(raw))["web_tools"]
    run = await active_run_for_session(db, session.id)
    if mode == "off":
        return False, run
    if mode == "all":
        return True, run
    research = run is not None and bool(await research_min_sources(db, run, await turn_phase(db, run)))
    return research, run


async def handle_codex_seat_search_admit(request: Request, db: AsyncSession) -> Response:
    context = await _codex_seat_context(request, db)
    if isinstance(context, Response):
        return context
    _identity, session, _decision = context
    body = await _json_body(request)
    if body is None or _commands(body) is None:
        return codex_seat_refused(refusal(STATE_DENIED, REASON_SEARCH_INVALID, http_status=400))
    allowed, run = await _search_allowed(db, session)
    if not allowed:
        return codex_seat_refused(refusal(STATE_DENIED, REASON_NOT_RESEARCH, http_status=403,
                                          hint="This Workspace limits web search (device_runs.tool_defaults."
                                               "web_tools); an admin can open it."))
    commands = json.dumps(_commands(body), ensure_ascii=False)[:MAX_RECORDED_COMMANDS_CHARS]
    row = ToolCall(session_id=session.id, tool_name=SEARCH_TOOL, status="pending", created_at=utc_now(),
                   parameters={"source": TOOL_CALL_SOURCE_GATEWAY, "commands": commands,
                               "run_id": run.id if run is not None else None,
                               "node_id": run.current_node_id if run is not None else None})
    db.add(row)
    await db.commit()
    return JSONResponse({"ticket": row.id})


async def handle_codex_seat_search_report(request: Request, db: AsyncSession) -> Response:
    context = await _codex_seat_context(request, db)
    if isinstance(context, Response):
        return context
    _identity, session, _decision = context
    body = await _json_body(request) or {}
    ticket = str(body.get("ticket") or "")
    row = await db.get(ToolCall, ticket) if ticket else None
    if row is None or row.session_id != session.id or row.tool_name != SEARCH_TOOL or row.status != "pending":
        return codex_seat_refused(refusal(STATE_DENIED, REASON_TICKET_INVALID, http_status=403))
    status = body.get("status_code")
    ok = isinstance(status, int) and 200 <= status < 300
    row.status = "success" if ok else "error"
    row.result = {"is_error": not ok, "status_code": status if isinstance(status, int) else None}
    await db.commit()
    return JSONResponse({"recorded": True})


__all__ = ["SEARCH_TOOL", "handle_codex_seat_search_admit", "handle_codex_seat_search_report"]
