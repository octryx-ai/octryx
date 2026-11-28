"""The explicit capability profile of every internal worker that dispatches tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.tools.capability_requirements import CAPABILITY_DELIVER, CAPABILITY_READ_ONLY

from .classes import RUN_CAPABILITY_CLASS_KEY
from .declared import (
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_WORKER_PROFILE,
    DeclaredRunCapability,
    capped_by_parent,
)

WORKER_CAPABILITY_PROFILES: Mapping[str, str] = {
    # The Teams voice agent answers questions from its enabled (read) tools.
    "call_agent": CAPABILITY_READ_ONLY,
    # Posts the reporter's Teams answer as a Jira comment: an external write.
    "proactive_teams_reply": CAPABILITY_DELIVER,
    "mcp_governed_knowledge": CAPABILITY_READ_ONLY,
    # A custom REST write reaches an external system; every call waits for approval (``device_external_write``).
    "mcp_rest_call": CAPABILITY_DELIVER,
    # A registry tool on the session MCP endpoint: every write or admin call waits for a person's approval in Octryx.
    "mcp_session": CAPABILITY_DELIVER,
    "pull_request_host_read": CAPABILITY_READ_ONLY,
    # Connector and admin connection tests read the remote system only.
    "connector_health_check": CAPABILITY_READ_ONLY,
    # The code graph's mirror fetches a repository with the Workspace connection's credentials: a read.
    "code_mirror_fetch": CAPABILITY_READ_ONLY,
    "webhook_event": CAPABILITY_READ_ONLY,
    "runtime_comparison": CAPABILITY_READ_ONLY,
    # A step started from a parent run is capped by it.
    "agent_chain_step": CAPABILITY_READ_ONLY,
    "channel_router": CAPABILITY_READ_ONLY,
    # A worker monitor's triggered action, including ``auto_fix`` (no change grant exists yet).
    "worker_monitor_action": CAPABILITY_READ_ONLY,
}


def worker_run_capability(worker_key: str, *, parent_context: Any = None) -> DeclaredRunCapability:
    key = str(worker_key or "").strip()
    capability_class = WORKER_CAPABILITY_PROFILES.get(key)
    if capability_class is None:
        raise ValueError(
            "Unregistered worker capability profile. Add it to services/run_capability/worker_profiles.py."
        )
    declared = DeclaredRunCapability(capability_class=capability_class, source=SOURCE_WORKER_PROFILE)
    state = getattr(parent_context, "run_capability", None) if parent_context is not None else None
    parent_class = state.get(RUN_CAPABILITY_CLASS_KEY) if isinstance(state, dict) else None
    return capped_by_parent(declared, parent_class)


def worker_tool_context_state(worker_key: str, *, parent_context: Any = None) -> dict[str, Any]:
    state = worker_run_capability(worker_key, parent_context=parent_context).tool_context_state()
    state["worker"] = str(worker_key)
    return state


def worker_session_capability_metadata(worker_key: str) -> dict[str, Any]:
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: worker_run_capability(worker_key).to_metadata()}


__all__ = [
    "WORKER_CAPABILITY_PROFILES",
    "worker_run_capability",
    "worker_session_capability_metadata",
    "worker_tool_context_state",
]
