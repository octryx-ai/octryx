"""What each kind of caller does with an Agent Definition resolution.

:mod:`app.services.agent_definition_execution` answers *what content
executes*; this module answers *what happens when it cannot*. The three call-site
classes need three different explicit answers to the same refusal, and keeping them
together is what stops one of them from quietly growing a fallback:

``require_execution_payload``
    A request path that requires an agent: 404 for a missing definition, 409 with a
    typed code for a refusal.

``execution_payload_or_none``
    A request path that tolerates *no* selected agent, but not a refused one.

``require_background_execution_payload``
    A scheduler or worker path with no caller to answer: the run fails
    with :class:`AgentDefinitionExecutionError`, which the caller persists as typed
    state on the task run and the step.

It also owns the canonical metadata entry recorded under
``RESOLUTION_METADATA_KEY`` by sessions, task runs, and the turn trace, so
provenance outlives the in-memory payload.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from .agent_definition_execution_states import (
    PAYLOAD_MODE_KEY,
    PAYLOAD_REVISION_ID_KEY,
    PAYLOAD_REVISION_NUMBER_KEY,
    PAYLOAD_SOURCE_KEY,
    REFUSAL_CODES,
    REFUSAL_STATUSES,
    RESOLUTION_METADATA_KEY,
    STATUS_INACTIVE,
    STATUS_NEEDS_CONFIGURATION,
    STATUS_NEEDS_PUBLICATION,
    STATUS_NOT_FOUND,
    AgentDefinitionResolution,
)


class AgentDefinitionExecutionError(RuntimeError):
    """A background path refusing to execute. Typed code and identifiers only.

    Background execution has no caller to answer an HTTP status to, so the refusal
    is an exception the scheduler records on the run and the step. The message is
    built from a typed code and identifiers, which is what makes it safe to persist
    in ``task_run.error`` and a step log.
    """

    def __init__(self, resolution: AgentDefinitionResolution) -> None:
        self.resolution = resolution
        self.code = REFUSAL_CODES.get(resolution.status, resolution.status)
        super().__init__(
            f"{self.code} definition={resolution.definition_id or '-'} "
            f"mode={resolution.mode}"
        )

    def as_metadata(self) -> dict[str, Any]:
        return {"code": self.code, **self.resolution.as_metadata()}


def require_execution_payload(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    """Return the payload, or raise the explicit refusal for a request path.

    404 is "agent not found" (no visible definition). 409 is the explicit
    refusal: the definition is inactive, it has nothing published to execute, or the
    mode key names no known mode. Each is a state an owner or administrator can act
    on, not a missing resource.
    """
    if resolution.status in REFUSAL_STATUSES:
        raise HTTPException(status_code=409, detail=execution_refusal_detail(resolution))
    if resolution.status == STATUS_NOT_FOUND or resolution.payload is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return resolution.payload


def execution_payload_or_none(
    resolution: AgentDefinitionResolution,
) -> dict[str, Any] | None:
    """Payload for a request path that tolerates *no* selected agent.

    A missing definition stays what it always was — no agent payload, the turn
    runs as a plain chat turn. A refusal status is deliberately *not* collapsed into
    the same ``None``: silently downgrading an inactive, unpublished or misconfigured
    agent to "no agent" would be exactly the hidden fallback this boundary exists to
    remove, so it raises the explicit 409.
    """
    if resolution.status in REFUSAL_STATUSES:
        raise HTTPException(status_code=409, detail=execution_refusal_detail(resolution))
    return resolution.payload


def require_background_execution_payload(
    resolution: AgentDefinitionResolution,
    *,
    logger_: logging.Logger,
    subject: str,
) -> dict[str, Any] | None:
    """Payload for a scheduler/worker path, or a typed failure.

    Background execution cannot answer a 409, and it must not answer by running
    anyway: a scheduled task or task step run configured with an agent
    definition that is inactive or that published mode cannot execute **fails** with
    :class:`AgentDefinitionExecutionError`, which the caller persists on the run and
    the step. Continuing without the configured agent would silently execute a
    different (agent-less) turn than the one that was configured — a fail-open
    behaviour the draft default must not be used to excuse.

    A definition id that resolves to nothing at all returns ``None``: the run
    proceeds with no agent definition and a warning is logged. That case is a stale
    configuration reference rather than a publication state.
    """
    if resolution.status in REFUSAL_STATUSES:
        error = AgentDefinitionExecutionError(resolution)
        logger_.error(
            "[%s] refusing background execution: %s (definition=%s mode=%s)",
            subject,
            error.code,
            resolution.definition_id,
            resolution.mode,
        )
        raise error
    if resolution.status == STATUS_NOT_FOUND:
        logger_.warning(
            "[%s] agent_definition %s not found", subject, resolution.definition_id
        )
        return None
    return resolution.payload


def resolution_metadata(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    """The canonical metadata entry to merge into a session or task-run record."""
    return {RESOLUTION_METADATA_KEY: resolution.as_metadata()}


def payload_resolution_metadata(payload: dict[str, Any] | None) -> dict[str, Any]:
    """The same canonical entry, for a consumer that holds only the payload.

    The turn trace and the scheduler's step metadata are built from the execution
    payload rather than from the resolution object, so they read the four additive
    provenance keys back out here instead of re-deriving — or guessing — the source.
    The result is shaped like :func:`resolution_metadata` so both can be merged into
    a metadata dict interchangeably, and is empty when there is no agent definition.
    """
    if not payload:
        return {}
    return {
        RESOLUTION_METADATA_KEY: {
            "mode": str(payload.get(PAYLOAD_MODE_KEY) or ""),
            "source": str(payload.get(PAYLOAD_SOURCE_KEY) or ""),
            "revision_id": payload.get(PAYLOAD_REVISION_ID_KEY) or None,
            "revision_number": payload.get(PAYLOAD_REVISION_NUMBER_KEY) or None,
        }
    }


def execution_refusal_detail(resolution: AgentDefinitionResolution) -> dict[str, Any]:
    messages = {
        STATUS_NEEDS_PUBLICATION: (
            "This agent definition has no published revision and "
            "agent_definition_execution_mode is 'published'."
        ),
        STATUS_NEEDS_CONFIGURATION: (
            "agent_definition_execution_mode is set to a value that is not "
            "'published' or 'draft'."
        ),
        STATUS_INACTIVE: (
            "This agent is inactive, so it cannot start new turns. "
            "Activate it on its agent page to use it again."
        ),
    }
    return {
        "code": REFUSAL_CODES.get(resolution.status, resolution.status),
        "message": messages.get(resolution.status, ""),
        "definition_id": resolution.definition_id,
    }

__all__ = [
    "AgentDefinitionExecutionError",
    "execution_payload_or_none",
    "execution_refusal_detail",
    "payload_resolution_metadata",
    "require_background_execution_payload",
    "require_execution_payload",
    "resolution_metadata",
]
