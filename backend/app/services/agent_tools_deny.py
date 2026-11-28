"""An agent's ``tools_deny`` at dispatch, on every path. It narrows what runs, never only what the model sees."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

REASON_AGENT_TOOLS_DENY = "agent_tools_deny"
REFUSAL_POLICY = "agent_tools_deny"

#: Platform tool -> the Claude Code native tools that do the same thing. Explicit, closed, reviewed.
NATIVE_EQUIVALENTS: dict[str, frozenset[str]] = {
    "read_workspace_file": frozenset({"Read", "NotebookRead"}),
    "grep_workspace": frozenset({"Grep"}),
    "glob_workspace_files": frozenset({"Glob"}),
    "list_workspace_directory": frozenset({"LS"}),
    "web_fetch": frozenset({"WebFetch"}),
    "web_search": frozenset({"WebSearch"}),
    "bash": frozenset({"Bash"}),
    "write_workspace_file": frozenset({"Write"}),
    "edit_workspace_file": frozenset({"Edit"}),
    "multi_edit_workspace_file": frozenset({"MultiEdit"}),
}


def denied_tools(agent_definition: dict[str, Any] | None) -> frozenset[str]:
    return frozenset(str(item) for item in (agent_definition or {}).get("toolsDeny") or [] if str(item).strip())


def native_tool_denied(tool_name: str, denied: Iterable[str]) -> str | None:
    return next((tool for tool in sorted(set(denied)) if tool_name in NATIVE_EQUIVALENTS.get(tool, ())), None)


def _refusal(tool_name: str, *, denied_as: str | None = None) -> dict[str, Any]:
    named = f" (it stands for '{denied_as}')" if denied_as and denied_as != tool_name else ""
    return {"error": f"Tool '{tool_name}' was not run: the agent's published tools deny excludes it{named}.",
            "status": "denied", "tool_name": tool_name, "reason": REASON_AGENT_TOOLS_DENY}


def agent_tools_deny_refusal(tool_name: str, context: Any) -> dict[str, Any] | None:
    if tool_name not in denied_tools(getattr(context, "agent_definition", None)):
        return None
    from ..tools.results import annotate_tool_result_payload

    return annotate_tool_result_payload(tool_name, _refusal(tool_name), category="denied_by_policy",
                                        reason=REASON_AGENT_TOOLS_DENY, policy=REFUSAL_POLICY)


async def run_session_denied_tools(db: AsyncSession, session_key: str | None) -> frozenset[str]:
    from ..models import AgentPresence, Session
    from .workflow_runs.octryx.contract import run_contract, session_principal
    from .workflow_runs.records import active_run_for_session

    key = session_key.strip() if isinstance(session_key, str) else ""
    if not key:
        return frozenset()
    presence = (await db.execute(select(AgentPresence).where(AgentPresence.session_key == key))).scalar_one_or_none()
    run = await active_run_for_session(db, presence.session_id) if presence and presence.session_id else None
    session = await db.get(Session, presence.session_id) if run is not None else None
    phase = (await run_contract(db, run, principal=await session_principal(db, session), session=session)).get(
        "phase") if run is not None else None
    return frozenset(str(item) for item in dict((phase or {}).get("tools") or {}).get("deny") or [])


async def run_session_mcp_refusal(db: AsyncSession, session_key: str | None, tool_name: str
                                  ) -> dict[str, Any] | None:
    if tool_name not in await run_session_denied_tools(db, session_key):
        return None
    return _refusal(tool_name)


__all__ = [
    "NATIVE_EQUIVALENTS",
    "REASON_AGENT_TOOLS_DENY",
    "agent_tools_deny_refusal",
    "denied_tools",
    "native_tool_denied",
    "run_session_denied_tools",
    "run_session_mcp_refusal",
]
