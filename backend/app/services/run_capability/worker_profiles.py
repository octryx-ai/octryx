"""The explicit capability profile of every internal worker that dispatches tools.

An internal worker never picks a workflow, so its class comes from here: one closed entry per
worker, each a deliberate decision. An unregistered worker key raises (fail closed), exactly like
an unregistered dispatch owner. A worker that runs on behalf of another run (a tool that spawns it)
is capped by that run's class, so a worker profile never escalates the run that started it.

Programmatic ``run_agent`` callers are workers too: each records its profile as the session's
``declared_run_capability`` (:func:`worker_session_capability_metadata`), so its turn's execution
profile names the worker profile as its origin instead of running without one.
"""

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
    # Caches read-tool results ahead of the turn; the prefetch governance admits reads only.
    "prefetch_worker": CAPABILITY_READ_ONLY,
    # The Teams voice agent answers questions from its enabled (read) tools.
    "call_agent": CAPABILITY_READ_ONLY,
    # Posts the reporter's Teams answer as a Jira comment: an external write.
    "proactive_teams_reply": CAPABILITY_DELIVER,
    # Serves the governed Knowledge tools on the MCP surface.
    "mcp_governed_knowledge": CAPABILITY_READ_ONLY,
    # A device's ``rest_call`` (Knowledge MCP, ``mcp_rest_tools``): a custom REST write reaches an external system,
    # and every such call waits for a person's approval in Octryx (``tool_approval_gate``, ``device_external_write``).
    "mcp_rest_call": CAPABILITY_DELIVER,
    # Reads a sample Office document during live validation.
    # The PR-host refresh (secure_work/pull_requests): reads the PR, its builds and reviews.
    "pull_request_host_read": CAPABILITY_READ_ONLY,
    # Connector and admin connection tests read the remote system only.
    "connector_health_check": CAPABILITY_READ_ONLY,
    # The code graph's mirror fetches a repository with the Workspace connection's credentials: a read.
    "code_mirror_fetch": CAPABILITY_READ_ONLY,
    # Programmatic ``run_agent`` callers, each with the class it runs under.
    # The admin control-plane test chat probes a runtime with a diagnosis turn.
    "control_plane_test_chat": CAPABILITY_READ_ONLY,
    # An inbound webhook event starts a diagnosis turn.
    "webhook_event": CAPABILITY_READ_ONLY,
    # The runtime comparison replays one prompt on several runtimes.
    "runtime_comparison": CAPABILITY_READ_ONLY,
    # One step of an agent chain; a step started from a parent run is capped by it.
    "agent_chain_step": CAPABILITY_READ_ONLY,
    # A message from an external channel (Slack, Teams, ...) routed into a session.
    "channel_router": CAPABILITY_READ_ONLY,
    # A worker monitor's triggered action, including ``auto_fix`` (no change grant exists yet).
    "worker_monitor_action": CAPABILITY_READ_ONLY,
}


def worker_run_capability(worker_key: str, *, parent_context: Any = None) -> DeclaredRunCapability:
    """The worker's profile class, capped by the class of the run that started it."""
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
    """The ``ToolContext.run_capability`` state of a worker run."""
    state = worker_run_capability(worker_key, parent_context=parent_context).tool_context_state()
    state["worker"] = str(worker_key)
    return state


def worker_session_capability_metadata(worker_key: str) -> dict[str, Any]:
    """The session metadata that makes a worker's ``run_agent`` turns resolve its profile class."""
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: worker_run_capability(worker_key).to_metadata()}


__all__ = [
    "WORKER_CAPABILITY_PROFILES",
    "worker_run_capability",
    "worker_session_capability_metadata",
    "worker_tool_context_state",
]
